"""Session CLI verbs: attach, status, sessions ls/detach/takeover.

The CLI gate (T8) routes everything outside the unbound allowlist into
``cmd_status`` / ``cmd_attach`` first so a fresh tab without a session
gets a structured prompt rather than an opaque error.

Output formats use literal template strings so tests can string-match.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from astrid.core.project.current_run import read_current_run
from astrid.core.project.paths import project_dir, resolve_projects_root
from astrid.core.project.project import ProjectError, require_project
from astrid.core.timeline import crud as timeline_crud
from astrid.core.timeline.defaults import read_project_default
from astrid.core.timeline.paths import find_timeline_by_slug, find_timeline_slug_for_ulid
from astrid.core.session.binding import (
    ASTRID_SESSION_ID_ENV,
    SessionBindingError,
    resolve_current_session,
)
from astrid.core.session.config import resolve_default_project, set_default_project
from astrid.core.session.constants import STUCK_NO_EVENT_SECONDS
from astrid.core.session.discovery import discover_projects
from astrid.core.session.identity import (
    Identity,
    IdentityError,
    bootstrap_identity,
    read_identity,
    validate_agent_slug,
)
from astrid.core.session.lease import (
    LeaseError,
    bump_epoch_and_swap_session,
    claim_orphan_lease,
    read_lease,
)
from astrid.core.session.model import Session, SessionRole
from astrid.core.session.paths import (
    session_path,
    sessions_dir,
)
from astrid.core.session.ulid import generate_ulid
from astrid.core.task.events import EVENTS_FILENAME, read_events

# ----- Templates --------------------------------------------------------
#
# Tests assert on these literal strings; keep them stable.

ATTACH_HEADER = "session created"
EXPORT_LINE_TEMPLATE = "export ASTRID_SESSION_ID={sid}"
TAKEOVER_HINT_READER = "another session ({writer}) holds this run; take over with: astrid sessions takeover {run_id}"
TAKEOVER_HINT_ORPHAN = "lease is orphan-pending; claim it with: astrid sessions takeover {run_id}"
STATUS_UNBOUND_HEADER = "no session bound"
ATTACH_SUGGESTION_TEMPLATE = "  astrid attach {slug}"
NO_PROJECTS_FOUND = "no projects discovered under the projects root"
FIRST_RUN_PROMPT_HEADER = "first-run bootstrap: no agent identity on this machine"

NONE_PLACEHOLDER = "(none)"


# ----- Helpers ----------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _parse_agent_override(raw: str) -> str:
    """Parse ``agent:<slug>`` from ``--as`` argument; raise on malformed."""

    if not raw.startswith("agent:"):
        raise ValueError(f"--as must be of form 'agent:<slug>', got {raw!r}")
    return validate_agent_slug(raw[len("agent:") :])


def _ensure_identity(*, prompt: Any = None, out: Any = None) -> Identity:
    """Return the on-disk identity, triggering first-run bootstrap if absent.

    ``prompt`` is forwarded to :func:`bootstrap_identity`; ``None`` lets
    that helper resolve :func:`builtins.input` lazily.
    """

    if out is None:
        out = sys.stdout
    existing = read_identity()
    if existing is not None:
        return existing
    print(FIRST_RUN_PROMPT_HEADER, file=out)
    return bootstrap_identity(prompt=prompt)


def _list_session_files() -> list[Session]:
    sessions: list[Session] = []
    sdir = sessions_dir()
    if not sdir.exists():
        return sessions
    for entry in sorted(sdir.iterdir()):
        if entry.suffix != ".json":
            continue
        try:
            sessions.append(Session.from_json(entry))
        except Exception:  # noqa: BLE001 — corrupt files surface in cmd_status
            continue
    return sessions


def _last_event_ts(run_dir: Path) -> str | None:
    events_path = run_dir / EVENTS_FILENAME
    if not events_path.exists() or events_path.stat().st_size == 0:
        return None
    events = read_events(events_path)
    if not events:
        return None
    ts = events[-1].get("ts")
    return ts if isinstance(ts, str) else None


def _is_target_warm(run_dir: Path) -> bool:
    """A target run is 'warm' if its events.jsonl was modified within
    STUCK_NO_EVENT_SECONDS of now. Warm targets require --force to take
    over. We use file mtime rather than parsed event ts so the check
    works whether or not the event carries a timestamp field.
    """

    events_path = run_dir / EVENTS_FILENAME
    if not events_path.exists() or events_path.stat().st_size == 0:
        return False
    age = time.time() - events_path.stat().st_mtime
    return age < STUCK_NO_EVENT_SECONDS


# ----- cmd_attach -------------------------------------------------------


def cmd_attach(args: argparse.Namespace, *, out: Any = None) -> int:
    if out is None:
        out = sys.stdout
    try:
        identity = _ensure_identity(out=out)
    except IdentityError as exc:
        print(f"attach: {exc}", file=sys.stderr)
        return 2
    agent_id = identity.agent_id
    if args.as_agent:
        try:
            agent_id = _parse_agent_override(args.as_agent)
        except (ValueError, IdentityError) as exc:
            print(f"attach: {exc}", file=sys.stderr)
            return 2

    if args.session:
        # Resume an existing session by id; the env var still has to be
        # exported by the operator after this call.
        try:
            session = Session.from_json(session_path(args.session))
        except FileNotFoundError:
            print(
                f"attach: no session file for id {args.session!r}",
                file=sys.stderr,
            )
            return 2
        session = session.with_changes(last_used_at=_now_iso())
        session.to_json(session_path(session.id))
        sid = session.id
        slug = session.project
        # Resumed sessions: use the stored timeline info; do NOT backfill.
        resolved_timeline_slug = session.timeline
        resolved_timeline_id = session.timeline_id
    else:
        explicit_project = args.project is not None
        slug = args.project or resolve_default_project()
        if not slug:
            projects = discover_projects()
            print("attach: no project specified and no default project configured", file=sys.stderr)
            if projects:
                print("", file=sys.stderr)
                print("projects:", file=sys.stderr)
                for project_slug in projects:
                    print(f"  {project_slug}", file=sys.stderr)
                print("", file=sys.stderr)
                print("choose one:", file=sys.stderr)
                print(f"  astrid attach {projects[0]}", file=sys.stderr)
                print(f"  astrid attach {projects[0]} --default", file=sys.stderr)
                print(f"  astrid projects default {projects[0]}", file=sys.stderr)
            else:
                print("no projects discovered under the projects root", file=sys.stderr)
                print("create one with: astrid projects create <slug>", file=sys.stderr)
            return 2
        try:
            require_project(slug)
        except ProjectError:
            projects = discover_projects()
            if args.project:
                print(f"attach: project '{slug}' was not found under the current projects root", file=sys.stderr)
            else:
                print(
                    f"attach: configured default project '{slug}' was not found under the current projects root",
                    file=sys.stderr,
                )
            if projects:
                print("", file=sys.stderr)
                print("projects:", file=sys.stderr)
                for project_slug in projects:
                    print(f"  {project_slug}", file=sys.stderr)
                print("", file=sys.stderr)
                print("choose one:", file=sys.stderr)
                print(f"  astrid attach {projects[0]} --default", file=sys.stderr)
                print(f"  astrid projects default {projects[0]}", file=sys.stderr)
            else:
                print("no projects discovered under the projects root", file=sys.stderr)
                print("create one with: astrid projects create <slug>", file=sys.stderr)
            return 2
        sid = generate_ulid()
        # Resolve timeline: explicit flag → project default → prompt / error.
        resolved_timeline_id: str | None = None
        if args.timeline:
            found = find_timeline_by_slug(slug, args.timeline)
            if found is None:
                print(
                    f"attach: timeline '{args.timeline}' not found in project '{slug}'",
                    file=sys.stderr,
                )
                return 2
            resolved_timeline_id = found[0]
            resolved_timeline_slug = args.timeline
        else:
            default_ulid = read_project_default(slug)
            if default_ulid is not None:
                default_slug = find_timeline_slug_for_ulid(slug, default_ulid)
                if default_slug is not None:
                    resolved_timeline_id = default_ulid
                    resolved_timeline_slug = default_slug
                    print(
                        f"Using default timeline: {default_slug}. "
                        f"Use --timeline to override.",
                        file=sys.stderr,
                    )
                else:
                    resolved_timeline_slug = None
            else:
                resolved_timeline_slug = None

            if resolved_timeline_id is None:
                # No explicit flag, no default → prompt or error.
                from astrid.core.timeline.crud import list_timelines

                available = list_timelines(slug)
                if not available:
                    # Bootstrap case: no timelines at all.  Proceed without one;
                    # the user can create timelines once attached.
                    print(
                        f"attach: no timelines exist for project '{slug}' yet; "
                        "session bound without a timeline. "
                        "Run `astrid timelines create <slug>` to make one.",
                        file=sys.stderr,
                    )
                    resolved_timeline_slug = None
                elif len(available) == 1:
                    choice = available[0]
                    found = find_timeline_by_slug(slug, choice.slug)
                    if found is None:
                        print(
                            f"attach: timeline '{choice.slug}' not found in project '{slug}'",
                            file=sys.stderr,
                        )
                        return 2
                    resolved_timeline_id = found[0]
                    resolved_timeline_slug = choice.slug
                    print(
                        f"Using only timeline: {choice.slug}. "
                        "Use --timeline to override.",
                        file=sys.stderr,
                    )
                elif sys.stdin.isatty():
                    print("Available timelines:", file=sys.stderr)
                    for t in available:
                        print(f"  {t.slug}  ({t.name})", file=sys.stderr)
                    try:
                        choice = input("Choose a timeline slug: ").strip()
                    except (EOFError, KeyboardInterrupt):
                        print("", file=sys.stderr)
                        print("attach: cancelled", file=sys.stderr)
                        return 2
                    found = find_timeline_by_slug(slug, choice)
                    if found is None:
                        print(
                            f"attach: timeline '{choice}' not found",
                            file=sys.stderr,
                        )
                        return 2
                    resolved_timeline_id = found[0]
                    resolved_timeline_slug = choice
                else:
                    print(
                        "no default timeline; pass --timeline <slug>",
                        file=sys.stderr,
                    )
                    return 2

    # Determine the role from current_run.json + lease.
    on_disk_run_id = read_current_run(slug)
    role: SessionRole = "writer"
    takeover_hint: str | None = None
    if on_disk_run_id is not None:
        run_dir = project_dir(slug) / "runs" / on_disk_run_id
        lease = read_lease(run_dir)
        attached = lease.get("attached_session_id")
        if attached is None:
            role = "orphan-pending"
            takeover_hint = TAKEOVER_HINT_ORPHAN.format(run_id=on_disk_run_id)
        elif attached != sid:
            role = "reader"
            takeover_hint = TAKEOVER_HINT_READER.format(
                writer=attached, run_id=on_disk_run_id
            )
        # else: same session id (resumed) → writer

    if not args.session:
        session = Session(
            id=sid,
            project=slug,
            timeline=resolved_timeline_slug,
            timeline_id=resolved_timeline_id,
            run_id=on_disk_run_id,
            agent_id=agent_id,
            attached_at=_now_iso(),
            last_used_at=_now_iso(),
            role=role,
        )
        session.to_json(session_path(sid))
        if getattr(args, "set_default", False):
            set_default_project(
                slug,
                scope="user" if getattr(args, "user_default", False) else "workspace",
            )

    print(ATTACH_HEADER, file=out)
    if not args.session and getattr(args, "set_default", False):
        scope = "user" if getattr(args, "user_default", False) else "workspace"
        label = "saved default project" if explicit_project else "using default project"
        print(f"{label} ({scope}): {slug}", file=out)
    print(EXPORT_LINE_TEMPLATE.format(sid=sid), file=out)
    print(f"project: {slug}", file=out)
    print(f"timeline: {resolved_timeline_slug or NONE_PLACEHOLDER}", file=out)
    print(f"run: {on_disk_run_id or NONE_PLACEHOLDER}", file=out)
    print(f"role: {role}", file=out)
    if takeover_hint is not None:
        print(takeover_hint, file=out)
    return 0


# ----- cmd_sessions_ls --------------------------------------------------


def cmd_sessions_ls(args: argparse.Namespace, *, out: Any = None) -> int:
    if out is None:
        out = sys.stdout
    sessions = _list_session_files()
    if not sessions:
        print("no sessions", file=out)
        return 0
    for s in sessions:
        timeline_display = s.timeline
        if timeline_display is None and s.timeline_id is not None:
            timeline_display = find_timeline_slug_for_ulid(
                s.project, s.timeline_id
            )
        print(
            f"{s.id}  project={s.project}  "
            f"timeline={timeline_display or NONE_PLACEHOLDER}  "
            f"run={s.run_id or NONE_PLACEHOLDER}  last_used={s.last_used_at}",
            file=out,
        )
    return 0


# ----- cmd_sessions_detach ----------------------------------------------


def cmd_sessions_detach(args: argparse.Namespace, *, out: Any = None) -> int:
    if out is None:
        out = sys.stdout
    target = args.session_id
    if not target:
        env_id = sys.modules["os"].environ.get(ASTRID_SESSION_ID_ENV)
        if not env_id:
            print(
                "detach: no session bound (ASTRID_SESSION_ID unset); pass a session id",
                file=sys.stderr,
            )
            return 2
        target = env_id
    path = session_path(target)
    if not path.exists():
        print(f"detach: no session file for id {target!r}", file=sys.stderr)
        return 2
    path.unlink()
    print(f"detached {target}", file=out)
    return 0


# ----- cmd_sessions_takeover --------------------------------------------


def cmd_sessions_takeover(args: argparse.Namespace, *, out: Any = None) -> int:
    if out is None:
        out = sys.stdout
    try:
        current = resolve_current_session()
    except SessionBindingError as exc:
        print(f"takeover: {exc}", file=sys.stderr)
        return 2
    if current is None:
        print(
            "takeover: caller not bound (ASTRID_SESSION_ID unset); attach first",
            file=sys.stderr,
        )
        return 2

    # Resolve the target: try session-id first, then run-id within the
    # caller's project.
    target_path = session_path(args.target)
    target_run_dir: Path | None = None
    prev_session_id: str | None = None
    if target_path.exists():
        target_sess = Session.from_json(target_path)
        if target_sess.run_id is None:
            print(
                f"takeover: target session {args.target!r} is not bound to a run",
                file=sys.stderr,
            )
            return 2
        target_run_dir = (
            project_dir(target_sess.project) / "runs" / target_sess.run_id
        )
        prev_session_id = target_sess.id
    else:
        # Treat as a run id within the caller's project.
        candidate = project_dir(current.project) / "runs" / args.target
        if not (candidate / "events.jsonl").exists():
            print(
                f"takeover: {args.target!r} matches neither a session id nor a run id "
                f"in project {current.project!r}",
                file=sys.stderr,
            )
            return 2
        target_run_dir = candidate
        lease = read_lease(target_run_dir)
        prev_session_id = lease.get("attached_session_id")

    assert target_run_dir is not None
    lease = read_lease(target_run_dir)
    if lease.get("attached_session_id") is None:
        try:
            updated = claim_orphan_lease(target_run_dir, new_session_id=current.id)
        except LeaseError as exc:
            print(f"takeover: {exc}", file=sys.stderr)
            return 2
        print(
            f"claimed orphan lease; writer_epoch={updated['writer_epoch']}, "
            f"writer={updated['attached_session_id']}",
            file=out,
        )
        return 0

    if _is_target_warm(target_run_dir) and not args.force:
        print(
            f"takeover: target wrote within the last {STUCK_NO_EVENT_SECONDS}s; "
            "may still be live elsewhere — confirm and re-run with --force",
            file=sys.stderr,
        )
        return 2

    updated = bump_epoch_and_swap_session(
        target_run_dir,
        new_session_id=current.id,
        prev_session_id=prev_session_id,
        reason="cli-takeover",
    )
    print(
        f"took over; writer_epoch={updated['writer_epoch']}, "
        f"writer={updated['attached_session_id']}",
        file=out,
    )
    return 0


# ----- cmd_status -------------------------------------------------------


def cmd_status(args: argparse.Namespace, *, out: Any = None) -> int:
    if out is None:
        out = sys.stdout
    try:
        session = resolve_current_session()
    except SessionBindingError as exc:
        print(f"status: {exc}", file=sys.stderr)
        return 2

    if session is None:
        return _render_unbound_status(out=out)
    return _render_bound_status(session, out=out)


def _render_unbound_status(*, out: Any) -> int:
    print(STATUS_UNBOUND_HEADER, file=out)
    default = resolve_default_project()
    projects = discover_projects()
    default_is_available = bool(default and default in projects)
    if default_is_available:
        print(f"default project: {default}", file=out)
    elif default:
        print(f"configured default project: {default} (not found under current projects root)", file=out)
    if not projects:
        print(NO_PROJECTS_FOUND, file=out)
        print("create one with: astrid projects create <slug>", file=out)
        return 0
    print("", file=out)
    print("start:", file=out)
    if default_is_available:
        print("  astrid attach              # attach default project", file=out)
    elif len(projects) == 1:
        print(f"  astrid attach {projects[0]}", file=out)
    else:
        print("  astrid attach <project>", file=out)
    print("", file=out)
    print("discovered projects:", file=out)
    for slug in projects:
        print(ATTACH_SUGGESTION_TEMPLATE.format(slug=slug), file=out)
    print("", file=out)
    print("manage:", file=out)
    print("  astrid projects ls", file=out)
    if projects:
        print(f"  astrid projects default {projects[0]}", file=out)
    print("", file=out)
    print("after attach:", file=out)
    _print_discovery_hints(out=out)
    return 0


def _print_discovery_hints(*, out: Any) -> None:
    print("  astrid skills list          # discover pack skills and install state", file=out)
    print("  astrid orchestrators list   # discover workflows", file=out)
    print("  astrid executors list       # discover concrete tools", file=out)
    print("  astrid elements list        # discover render building blocks", file=out)


def _render_bound_status(session: Session, *, out: Any) -> int:
    identity = read_identity()
    agent_id = identity.agent_id if identity else session.agent_id
    # Try to pick up an on-disk run_id update (auto-rebind preview without
    # actually mutating the session file — that's WriterContext's job).
    on_disk_run_id = read_current_run(session.project)
    run_id = on_disk_run_id or session.run_id

    # Resolve timeline slug from timeline_id when needed.
    timeline_slug = session.timeline
    timeline_final_count = 0
    # Also fall back to project default when session has no timeline binding.
    if timeline_slug is None and session.timeline_id is None:
        from astrid.core.timeline.defaults import read_project_default

        default_ulid = read_project_default(session.project)
        if default_ulid is not None:
            default_slug = find_timeline_slug_for_ulid(
                session.project, default_ulid
            )
            if default_slug is not None:
                timeline_slug = default_slug
    if timeline_slug is not None or session.timeline_id is not None:
        if timeline_slug is None and session.timeline_id is not None:
            timeline_slug = find_timeline_slug_for_ulid(
                session.project, session.timeline_id
            )
        if timeline_slug is not None:
            try:
                data = timeline_crud.show_timeline(session.project, timeline_slug)
                if data is not None:
                    timeline_final_count = len(data["manifest"].final_outputs)
            except Exception:
                pass  # best-effort; don't break status for a corrupt timeline

    timeline_line = f"timeline: {timeline_slug or NONE_PLACEHOLDER}"
    if timeline_final_count > 0:
        timeline_line += f" ({timeline_final_count} final output{'s' if timeline_final_count != 1 else ''})"

    print(f"session: {session.id}", file=out)
    print(f"agent: {agent_id}", file=out)
    print(f"project: {session.project}", file=out)
    print(timeline_line, file=out)
    print(f"run: {run_id or NONE_PLACEHOLDER}", file=out)

    current_step = NONE_PLACEHOLDER
    last_five: list[dict[str, Any]] = []
    inbox_count = 0
    role_line = f"role: {session.role}"
    takeover_hint: str | None = None

    if run_id is not None:
        run_dir = project_dir(session.project) / "runs" / run_id
        events_path = run_dir / EVENTS_FILENAME
        if events_path.exists():
            events = read_events(events_path)
            last_five = events[-5:]
            # "current step" proxy: latest step_dispatched event, else last
            # event kind. Sprint 1 is not the step-model rewrite (Sprint 3).
            for ev in reversed(events):
                if ev.get("kind") == "step_dispatched":
                    current_step = str(ev.get("plan_step_id") or ev.get("kind"))
                    break
            else:
                if events:
                    current_step = str(events[-1].get("kind", NONE_PLACEHOLDER))
        inbox_dir = run_dir / "inbox"
        if inbox_dir.exists():
            inbox_count = sum(1 for p in inbox_dir.iterdir() if p.is_file())
        # Role correction from the lease (the on-disk session role is just
        # a hint; the lease is authoritative).
        try:
            lease = read_lease(run_dir)
        except LeaseError:
            lease = {"attached_session_id": None}
        attached = lease.get("attached_session_id")
        if attached is None:
            role_line = "role: orphan-pending"
            takeover_hint = TAKEOVER_HINT_ORPHAN.format(run_id=run_id)
        elif attached != session.id:
            role_line = "role: reader"
            takeover_hint = TAKEOVER_HINT_READER.format(writer=attached, run_id=run_id)
        else:
            role_line = "role: writer"

    print(f"current step: {current_step}", file=out)
    print("recent events (last 5):", file=out)
    if not last_five:
        print(f"  {NONE_PLACEHOLDER}", file=out)
    else:
        for ev in last_five:
            ts = ev.get("ts", "")
            kind = ev.get("kind", "?")
            print(f"  {kind} @ {ts}", file=out)
    print(f"inbox: {inbox_count}", file=out)
    print(role_line, file=out)
    if takeover_hint is not None:
        print(takeover_hint, file=out)
    print("", file=out)
    print("task:", file=out)
    if run_id is not None:
        print(f"  astrid next --project {session.project}   # continue current task run", file=out)
    else:
        print(f"  astrid start <orchestrator-id> --project {session.project}   # start a task list", file=out)
    print("", file=out)
    print("discover:", file=out)
    _print_discovery_hints(out=out)
    return 0


# ----- argparse glue ----------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python3 -m astrid sessions")
    sub = parser.add_subparsers(dest="command", required=True)

    attach = sub.add_parser("attach", help="Bind the current tab to a project.")
    attach.add_argument("project", nargs="?")
    attach.add_argument("--timeline")
    attach.add_argument("--session", help="Resume an existing session id.")
    attach.add_argument("--as", dest="as_agent", help="Per-tab agent override (agent:<slug>).")
    attach.add_argument(
        "--default",
        action="store_true",
        dest="set_default",
        help="Remember this project as the workspace default.",
    )
    attach.add_argument(
        "--user",
        action="store_true",
        dest="user_default",
        help="With --default, write the user-wide default instead of the workspace default.",
    )
    attach.set_defaults(handler=cmd_attach)

    ls = sub.add_parser("ls", help="List sessions in ~/.astrid/sessions/.")
    ls.set_defaults(handler=cmd_sessions_ls)

    detach = sub.add_parser("detach", help="Detach a session (defaults to current tab).")
    detach.add_argument("session_id", nargs="?")
    detach.set_defaults(handler=cmd_sessions_detach)

    takeover = sub.add_parser("takeover", help="Take over a run lease.")
    takeover.add_argument("target", help="Session id or run id.")
    takeover.add_argument("--force", action="store_true", help="Allow takeover of a warm target.")
    takeover.set_defaults(handler=cmd_sessions_takeover)

    status = sub.add_parser("status", help="Print the current session breadcrumb.")
    status.set_defaults(handler=cmd_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args))
