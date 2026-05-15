"""Phase 5 lifecycle verbs: start/abort/status/runs ls/next; cmd_ack lives
in lifecycle_ack.py to keep both modules under the size budget.

cmd_runs_ls (FLAG-P5-006): natural completion does not clear active_run.json
in V1, so the lister surfaces only 'aborted' vs 'in-progress'.
cmd_start (SD-007): does not silently invoke compile when the pre-built JSON
manifest is missing — prints the compile recovery and returns non-zero.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional, Sequence

from astrid.core.project.jsonio import write_json_atomic
from astrid.core.project.paths import (
    project_dir,
    resolve_projects_root,
    validate_project_slug,
    validate_run_id,
)
from astrid.core.project.current_run import (
    clear_current_run,
    read_current_run,
    write_current_run,
)
from astrid.core.session.lease import (
    read_lease,
    release_writer_lease,
    write_lease_init,
)
# Backward-compat shim: gate.py and lifecycle_ack.py still import these via
# astrid.core.task.active_run during the T9 migration window. The shim
# writes the new on-disk shape internally.
from astrid.core.task.active_run import (
    clear_active_run,
    read_active_run,
    write_active_run,
)
from astrid.core.task.env import task_actor_env
from astrid.core.task.events import (
    EventLogError,
    _run_is_complete,
    append_event,
    make_run_aborted_event,
    make_run_completed_event,
    make_run_started_event,
    make_step_awaiting_fetch_event,
    make_step_completed_event,
    read_events,
)
from astrid.core.task.gate import TaskRunGateError, peek_current_step
from astrid.core.task.inbox import consume_inbox_entry, pending_count, scan_inbox
from astrid.core.task.plan import (
    STEP_PATH_SEP,
    RepeatForEach,
    Step,
    is_attested_kind,
    is_code_kind,
    is_group_step,
    compute_plan_hash,
    load_plan,
    step_dir_for_path,
)
from astrid.core.task.preamble import PROHIBITION_PREAMBLE
from astrid.core.timeline.defaults import read_project_default
from astrid.core.timeline.paths import find_timeline_by_slug, find_timeline_slug_for_ulid


_AGENT_MD_TEMPLATE = """{preamble}

QUALIFIED ORCHESTRATOR: {qualified_id}
RUN ID: {run_id}
TIMELINE ID: {timeline_id}

FIRST COMMAND (Sprint 1 / T15)
- astrid status                    # session breadcrumb; ALWAYS run first
- astrid attach {slug}     # bind this tab to {slug} if status reports unbound

RECOVERY COMMANDS
- See next legal action:    astrid next --project {slug}
- Acknowledge attested:     astrid ack <step> --project {slug} --decision approve [--agent <id> | --actor <name>]
- View run state:           astrid status --project {slug}
- End the run:              astrid abort --project {slug}
- Take over a stuck run:    astrid sessions takeover <run-id|session-id>
- Detach the current tab:   astrid sessions detach

STOP HOOK
- The `astrid hook stop` command is the Claude Code Stop-hook entry point.
  When wired into .claude/settings.json (see docs/HOOKS.md) it re-injects this
  preamble and the current step on every Stop boundary so the rules above
  stay live for the entire run. The hook is a silent no-op outside task mode.

INBOX SURFACE
- External processes (humans, scripts, other tools) signal completion of an
  attested step by dropping a JSON file into runs/{run_id}/inbox/.
- File shape:
    {{
      "step_id": "<id of the current attested step>",
      "decision": "approve" | "retry" | "abort",
      "evidence": {{ "<key>": "<non-empty string>", ... }},
      "submitted_at": "<ISO 8601 timestamp>",
      "submitted_by": "<external system or operator name>",
      "item_id": "<optional for_each item id>"
    }}
- Consume-on-next: astrid next reads inbox/, validates each file against
  the current cursor, and appends a step_attested / item_attested /
  cursor_rewind / run_aborted event before computing the next step.
- Agent attestations only — actor-ack steps must use `astrid ack` (the
  inbox file would be quarantined to inbox/.rejected/ otherwise).
- WARNING: `astrid next` is state-mutating when inbox/ has files.
"""


def _print_err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _resolve_packs_root(packs_root: Optional[Path]) -> Path:
    if packs_root is not None:
        return Path(packs_root)
    from astrid.orchestrate.compile import DEFAULT_PACKS_ROOT
    return DEFAULT_PACKS_ROOT


def _resolve_build_path(
    qualified_id: str,
    packs_root: Path,
) -> Path | None:
    """Find the compiled plan path for *qualified_id* using PackResolver.

    Returns *None* when the resolver cannot locate the pack, letting the
    caller fall back to the legacy ``<packs_root>/<pack>/build/<name>.json``
    convention.
    """
    pack, name = _qualified_split(qualified_id)
    try:
        from astrid.core.pack import PackResolver

        resolver = PackResolver(packs_root)
        pack_def = resolver.get_pack(pack)
        return pack_def.root / "build" / f"{name}.json"
    except Exception:
        return None


def _qualified_split(qualified_id: str) -> tuple[str, str]:
    if not isinstance(qualified_id, str) or "." not in qualified_id:
        raise ValueError(
            f"orchestrator id {qualified_id!r} must be '<pack>.<name>'"
        )
    pack, _, name = qualified_id.partition(".")
    if not pack or not name or "." in name:
        raise ValueError(
            f"orchestrator id {qualified_id!r} must be exactly '<pack>.<name>'"
        )
    return pack, name


def _generate_run_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"run-{stamp}-{secrets.token_hex(4)}"


# ---------------------------------------------------------------------------
# cmd_start
# ---------------------------------------------------------------------------


def cmd_start(
    argv: Sequence[str],
    *,
    packs_root: Optional[Path] = None,
    projects_root: Optional[Path] = None,
) -> int:
    parser = argparse.ArgumentParser(prog="astrid start", add_help=True)
    parser.add_argument("orchestrator_id", help="qualified id <pack>.<name>")
    parser.add_argument("--project", required=True, help="project slug")
    parser.add_argument("--name", default=None, help="optional run id (slug-validated)")
    parser.add_argument("--timeline", default=None, help="timeline slug")
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        return int(exc.code or 2)

    try:
        slug = validate_project_slug(args.project)
    except Exception as exc:
        _print_err(f"start: {exc}")
        return 1

    # Resolve timeline ULID (timeline_id) and slug for display.
    timeline_id: str | None = None
    timeline_slug: str | None = None
    if args.timeline is not None:
        found = find_timeline_by_slug(slug, args.timeline, root=projects_root)
        if found is None:
            _print_err(
                f"start: timeline {args.timeline!r} not found in project {slug!r}"
            )
            return 1
        timeline_id = found[0]
        timeline_slug = args.timeline
    else:
        default_ulid = read_project_default(slug, root=projects_root)
        if default_ulid is not None:
            resolved_slug = find_timeline_slug_for_ulid(slug, default_ulid, root=projects_root)
            if resolved_slug is not None:
                timeline_id = default_ulid
                timeline_slug = resolved_slug
                _print_err(
                    f"Using default timeline: {timeline_slug}. "
                    f"Use --timeline to override."
                )
    # If still no timeline, list available timelines and error — but allow the
    # bootstrap case (project.json absent) to proceed unbound, mirroring
    # ``astrid attach``'s zero-timeline handling. This keeps legacy callers
    # that pre-date Sprint 2's container model working until the project is
    # explicitly initialized.
    if timeline_id is None:
        from astrid.core.timeline.crud import list_timelines
        from astrid.core.project.paths import project_json_path
        available = list_timelines(slug, root=projects_root)
        if available:
            _print_err("No default timeline; pass --timeline <slug>. Available:")
            for ts in available:
                _print_err(f"  {ts.slug}  ({ts.name})")
            return 1
        if project_json_path(slug, root=projects_root).exists():
            _print_err(
                f"start: no timelines exist for project {slug!r}; "
                f"create one with `astrid timelines create <slug>`"
            )
            return 1
        # Bootstrap: project.json doesn't exist yet — proceed without a timeline
        # binding. The run record will carry timeline_id=None.

    try:
        pack, name = _qualified_split(args.orchestrator_id)
    except ValueError as exc:
        _print_err(f"start: {exc}")
        return 1

    if read_current_run(slug, root=projects_root) is not None:
        _print_err(
            f"start: active run already exists for project {slug!r}; "
            f"recovery: astrid abort --project {slug}"
        )
        return 1

    packs = _resolve_packs_root(packs_root)
    # Sprint 2 (T8): try resolver-backed build path first, then legacy.
    build_path = _resolve_build_path(args.orchestrator_id, packs)
    if build_path is None:
        build_path = packs / pack / "build" / f"{name}.json"
    if not build_path.is_file():
        _print_err(
            f"start: compiled plan not found at {build_path}; "
            f"recovery: astrid author compile {args.orchestrator_id}"
        )
        return 1

    try:
        compiled_payload = json.loads(build_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _print_err(f"start: failed to read {build_path}: {exc}")
        return 1

    proj_root = project_dir(slug, root=projects_root)
    proj_root.mkdir(parents=True, exist_ok=True)
    plan_path = proj_root / "plan.json"
    write_json_atomic(plan_path, compiled_payload)

    try:
        load_plan(plan_path)
    except Exception as exc:
        _print_err(f"start: compiled plan failed validation: {exc}")
        return 1

    plan_hash = compute_plan_hash(plan_path)

    if args.name is not None:
        try:
            run_id = validate_run_id(args.name)
        except Exception as exc:
            _print_err(f"start: --name {exc}")
            return 1
    else:
        run_id = _generate_run_id()

    run_dir = proj_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Lease-first ordering: any reader that observes current_run.json is
    # guaranteed to find a corresponding lease.json. The session id on the
    # lease is whatever ASTRID_SESSION_ID resolves to (CLI gate enforces
    # the session is bound before cmd_start dispatch); fall back to
    # 'legacy' for non-CLI callers that haven't migrated yet (tests etc).
    from astrid.core.session.binding import (
        SessionBindingError,
        resolve_current_session,
    )

    session_id_for_lease = "legacy"
    try:
        bound = resolve_current_session()
        if bound is not None:
            session_id_for_lease = bound.id
    except SessionBindingError:
        session_id_for_lease = "legacy"
    write_lease_init(
        run_dir,
        session_id=session_id_for_lease,
        plan_hash=plan_hash,
        timeline_id=timeline_id,
    )
    write_current_run(slug, run_id, root=projects_root)

    events_path = run_dir / "events.jsonl"
    actor = task_actor_env()
    append_event(events_path, make_run_started_event(run_id, plan_hash, actor=actor))

    agent_md = _AGENT_MD_TEMPLATE.format(
        preamble=PROHIBITION_PREAMBLE,
        qualified_id=args.orchestrator_id,
        run_id=run_id,
        slug=slug,
        timeline_id=timeline_id,
    )
    (run_dir / "AGENT.md").write_text(agent_md, encoding="utf-8")

    print(f"started {args.orchestrator_id}")
    print(f"  project:   {slug}")
    print(f"  timeline:  {timeline_slug}")
    print(f"  run-id:    {run_id}")
    print(f"  plan-hash: {plan_hash}")
    return 0


# ---------------------------------------------------------------------------
# cmd_abort
# ---------------------------------------------------------------------------


def cmd_abort(
    argv: Sequence[str],
    *,
    projects_root: Optional[Path] = None,
) -> int:
    parser = argparse.ArgumentParser(prog="astrid abort", add_help=True)
    parser.add_argument("--project", required=True, help="project slug")
    parser.add_argument("--reason", default=None, help="optional human-readable reason")
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        return int(exc.code or 2)

    try:
        slug = validate_project_slug(args.project)
    except Exception as exc:
        _print_err(f"abort: {exc}")
        return 1

    run_id = read_current_run(slug, root=projects_root)
    if run_id is None:
        # Idempotent — Phase 6 Stop-hook may invoke abort defensively.
        return 0

    run_dir = project_dir(slug, root=projects_root) / "runs" / run_id
    events_path = run_dir / "events.jsonl"
    append_event(events_path, make_run_aborted_event(run_id, reason=args.reason))
    # DEC-010: clear the pointer AND release the writer lease so the run
    # is fully detached. A follow-up takeover would now see the lease as
    # orphan-pending.
    clear_current_run(slug, root=projects_root)
    try:
        release_writer_lease(run_dir)
    except FileNotFoundError:
        pass
    print(f"aborted {run_id}")
    return 0


# ---------------------------------------------------------------------------
# cmd_status
# ---------------------------------------------------------------------------


def cmd_status(
    argv: Sequence[str],
    *,
    projects_root: Optional[Path] = None,
) -> int:
    parser = argparse.ArgumentParser(prog="astrid status", add_help=True)
    parser.add_argument("--project", required=True, help="project slug")
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        return int(exc.code or 2)

    try:
        slug = validate_project_slug(args.project)
    except Exception as exc:
        _print_err(f"status: {exc}")
        return 1

    active_run = read_active_run(slug, root=projects_root)
    if active_run is None:
        _print_err(
            f"status: no active run for project {slug!r}; "
            f"recovery: astrid start <orchestrator-id> --project {slug}"
        )
        return 1

    run_id = active_run["run_id"]
    plan_hash = active_run["plan_hash"]
    proj_root = project_dir(slug, root=projects_root)
    plan_path = proj_root / "plan.json"
    events_path = proj_root / "runs" / run_id / "events.jsonl"

    plan = load_plan(plan_path)
    events = read_events(events_path)
    peek = peek_current_step(
        plan, events, slug, project_root=proj_root, run_id=run_id
    )

    print(f"run-id:    {run_id}")
    print(f"plan-hash: {plan_hash}")
    if peek.exhausted or peek.step is None:
        print("current:   <run exhausted>")
    else:
        path_str = STEP_PATH_SEP.join(peek.path_tuple)
        kind = "nested" if is_group_step(peek.step) else (
            "attested" if is_attested_kind(peek.step) else "code"
        )
        suffix = ""
        if peek.iteration is not None:
            suffix += f"  iter={peek.iteration}"
        if peek.item_id is not None:
            suffix += f"  item={peek.item_id}"
        print(f"current:   {path_str} [{kind}] v{peek.step.version}{suffix}")
        if peek.step.produces:
            names = ", ".join(p.name for p in peek.step.produces)
            print(f"produces:  {names}")

    pending = pending_count(proj_root / "runs" / run_id)
    if pending > 0:
        print(f"inbox:     {pending} pending")

    print("recent events:")
    for ev in events[-5:]:
        kind = ev.get("kind", "?")
        ts = ev.get("ts", "")
        plan_step_id = ev.get("plan_step_id")
        if not isinstance(plan_step_id, str):
            path = ev.get("plan_step_path")
            plan_step_id = "/".join(path) if isinstance(path, list) else ""
        print(f"  {ts}  {kind}  {plan_step_id}")
    return 0


# ---------------------------------------------------------------------------
# cmd_next
# ---------------------------------------------------------------------------


def _format_ack_template(
    *, path_str: str, slug: str, ack_kind: str, has_repeat_for_each: bool
) -> str:
    identity = "--agent <id>" if ack_kind == "agent" else "--actor <name>"
    base = (
        f"astrid ack {path_str} --project {slug} --decision approve "
        f"{identity} [--evidence path ...]"
    )
    if has_repeat_for_each:
        base += " [--item <id>]"
    return base


def _find_step_by_path(plan, path_tuple):
    """Walk a TaskPlan to find the step at ``path_tuple`` (descending NestedStep
    children). Returns the step or None if the path does not resolve.
    """
    if not path_tuple:
        return None
    steps = plan.steps
    for segment in path_tuple[:-1]:
        match = next((s for s in steps if s.id == segment), None)
        if match is None or not is_group_step(match):
            return None
        steps = match.children or ()
    return next((s for s in steps if s.id == path_tuple[-1]), None)


def _completed_items_from_events(events, host_path):
    """Return the set of item ids that have a completed/attested event under
    ``host_path``. ``host_path`` is the STEP_PATH_SEP-joined string form.
    """
    path_list = host_path.split(STEP_PATH_SEP) if host_path else []
    completed: set[str] = set()
    for ev in events:
        if not isinstance(ev, dict):
            continue
        kind = ev.get("kind")
        if kind not in ("item_completed", "item_attested"):
            continue
        if ev.get("plan_step_path") != path_list:
            continue
        item_id = ev.get("item_id")
        if isinstance(item_id, str):
            completed.add(item_id)
    return completed


def cmd_next(
    argv: Sequence[str],
    *,
    projects_root: Optional[Path] = None,
) -> int:
    parser = argparse.ArgumentParser(prog="astrid next", add_help=True)
    parser.add_argument("--project", required=True, help="project slug")
    parser.add_argument(
        "--skip",
        action="store_true",
        help="skip the next step if it is optional=True (loops until a non-optional or exhausted)",
    )
    parser.add_argument(
        "--reason",
        default=None,
        help="optional reason recorded with each --skip event",
    )
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        return int(exc.code or 2)

    try:
        slug = validate_project_slug(args.project)
    except Exception as exc:
        # Preamble must precede every operator-facing message (SD-023).
        print(PROHIBITION_PREAMBLE)
        print()
        _print_err(f"next: {exc}")
        return 1

    # Always print preamble first, verbatim, every call (SD-023) — even on
    # error / exhausted paths so Stop-hook context re-injection is consistent.
    print(PROHIBITION_PREAMBLE)
    print()

    active_run = read_active_run(slug, root=projects_root)
    if active_run is None:
        _print_err(
            f"next: no active run for project {slug!r}; "
            f"recovery: astrid start <orchestrator-id> --project {slug}"
        )
        return 1

    run_id = active_run["run_id"]
    proj_root = project_dir(slug, root=projects_root)
    plan_path = proj_root / "plan.json"
    events_path = proj_root / "runs" / run_id / "events.jsonl"
    run_dir = proj_root / "runs" / run_id

    # FLAG-P8-005: cmd_next becomes state-mutating when inbox/ contains valid
    # files. Each entry is consumed best-effort so a single bad file cannot
    # crash the verb.
    for entry in scan_inbox(run_dir):
        try:
            consume_inbox_entry(
                run_dir, entry, slug=slug, projects_root=projects_root
            )
        except (TaskRunGateError, OSError, EventLogError):
            continue

    plan = load_plan(plan_path)
    events = read_events(events_path)
    peek = peek_current_step(
        plan, events, slug, project_root=proj_root, run_id=run_id
    )

    # --skip: emit step_skipped events for optional leaves until either the
    # next leaf is non-optional or the cursor exhausts. The very first
    # peek MUST be optional — refusing to start otherwise — but subsequent
    # iterations naturally stop at the first non-optional leaf and fall
    # through to print its dispatch.
    if args.skip:
        if peek.exhausted or peek.step is None:
            _print_err(
                f"next --skip: run is exhausted; recovery: astrid abort --project {slug}"
            )
            return 1
        if not peek.step.optional:
            _print_err(
                f"next --skip: cursor step {STEP_PATH_SEP.join(peek.path_tuple)!r} "
                f"is not optional; remove --skip to dispatch it"
            )
            return 1
        from astrid.core.task.events import make_step_skipped_event
        while (
            not (peek.exhausted or peek.step is None)
            and peek.step.optional
        ):
            skip_event = make_step_skipped_event(
                STEP_PATH_SEP.join(peek.path_tuple),
                actor_kind="agent",
                actor_id="cli",
                reason=args.reason,
            )
            append_event(events_path, skip_event)
            print(f"skipped {STEP_PATH_SEP.join(peek.path_tuple)}")
            events = read_events(events_path)
            peek = peek_current_step(
                plan, events, slug, project_root=proj_root, run_id=run_id
            )
        if peek.exhausted or peek.step is None:
            if _run_is_complete(plan, events):
                append_event(events_path, make_run_completed_event(run_id))
            return 0
        # Fall through into normal print of the now-non-optional step.

    if peek.exhausted or peek.step is None:
        if _run_is_complete(plan, events):
            append_event(events_path, make_run_completed_event(run_id))
        else:
            print(
                "run not complete: some steps still awaiting_fetch or in-flight",
                file=sys.stderr,
            )
        return 0

    path_str = STEP_PATH_SEP.join(peek.path_tuple)

    if is_code_kind(peek.step):
        print(f"run: {peek.step.command}")
        print(
            "(rerun the same command if it failed; the gate detects re-entry "
            "and skips a duplicate step_dispatched event.)"
        )
    elif is_attested_kind(peek.step):
        print(peek.step.instructions or peek.step.command or "")
        print()
        # peek.step.repeat is None when the leaf is the body of a repeat
        # frame (the body is a clone with repeat stripped) — peek.item_id
        # being set is the reliable signal that we're inside a for_each
        # host. Fall back to looking up the host in the plan when item_id
        # is None to handle a top-level for_each that hasn't dispatched yet.
        host_has_for_each = peek.item_id is not None
        if not host_has_for_each:
            host_step = _find_step_by_path(plan, peek.path_tuple)
            if host_step is not None and isinstance(
                getattr(host_step, "repeat", None), RepeatForEach
            ):
                host_has_for_each = True
        print(
            _format_ack_template(
                path_str=path_str,
                slug=slug,
                ack_kind=(peek.step.ack.kind if peek.step.ack is not None else "agent"),
                has_repeat_for_each=host_has_for_each,
            )
        )
    else:
        # Defensive: peek_current_step should never surface a NestedStep.
        _print_err(f"next: unexpected step kind {type(peek.step).__name__}")
        return 1

    # Iteration ledger: at peek.iteration == N (>=2), read iteration N-1's
    # cumulative feedback.json (written by write_iteration_feedback).
    if peek.iteration is not None and peek.iteration >= 2:
        prev_iter = peek.iteration - 1
        try:
            prev_dir = step_dir_for_path(
                slug,
                run_id,
                peek.path_tuple,
                step_version=1,
                iteration=prev_iter,
                root=projects_root,
            )
        except Exception:
            prev_dir = None
        if prev_dir is not None:
            feedback_path = prev_dir / "feedback.json"
            if feedback_path.is_file():
                try:
                    payload = json.loads(feedback_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    payload = None
                if isinstance(payload, list):
                    print()
                    print(f"feedback ledger (through iteration {prev_iter}):")
                    for idx, entry in enumerate(payload, start=1):
                        print(f"  [{idx}] {entry}")

    # for_each item ledger: when peek.item_id is set, the leaf is the body
    # step inside a for_each frame; peek.path_tuple matches the host path
    # because _make_item_frame uses path_prefix = parent_prefix and the body
    # carries the host's id. Look the host step up directly from the plan
    # (peek does not persist for_each_expanded to events.jsonl, so
    # derive_cursor's for_each_progress would be empty here).
    if peek.item_id is not None:
        host_path = STEP_PATH_SEP.join(peek.path_tuple)
        host_step = _find_step_by_path(plan, peek.path_tuple)
        items: list[str] = []
        if host_step is not None and isinstance(
            getattr(host_step, "repeat", None), RepeatForEach
        ):
            host_for_each: RepeatForEach = host_step.repeat  # type: ignore[assignment]
            if host_for_each.items_source == "static":
                items = list(host_for_each.items)
            # Dynamic items source — items are resolved at gate dispatch from
            # a sibling produces JSON file. peek shares the same resolution
            # path; if events.jsonl has a for_each_expanded event for this
            # host (because dispatch ran earlier) we can recover items from
            # there instead.
        if not items:
            for ev in events:
                if (
                    isinstance(ev, dict)
                    and ev.get("kind") == "for_each_expanded"
                    and ev.get("plan_step_path") == list(peek.path_tuple)
                ):
                    raw = ev.get("item_ids") or []
                    if isinstance(raw, list):
                        items = [str(x) for x in raw]
                    break
        completed = _completed_items_from_events(events, host_path)
        if items:
            print()
            print(f"for_each items (host {host_path}):")
            for item in items:
                marker = "x" if item in completed else " "
                star = "  <- next" if item == peek.item_id else ""
                print(f"  [{marker}] {item}{star}")

    return 0


# ---------------------------------------------------------------------------
# cmd_runs_ls
# ---------------------------------------------------------------------------


def _summarize_run_dir(run_dir: Path) -> tuple[str, str, str]:
    """Return (status, last_event_kind, last_ts) for a run directory.

    Status:
    - ``completed`` — terminal ``run_completed`` event present (S5a contract).
    - ``aborted`` — terminal ``run_aborted`` event present (S1 contract).
    - ``in-flight`` — neither terminal event yet; the run is still being driven.
    """
    events_path = run_dir / "events.jsonl"
    if not events_path.is_file():
        return "in-flight", "", ""
    events = read_events(events_path)
    if not events:
        return "in-flight", "", ""
    last = events[-1]
    last_kind = str(last.get("kind", ""))
    last_ts = str(last.get("ts", ""))
    if last_kind == "run_aborted":
        status = "aborted"
    elif last_kind == "run_completed":
        status = "completed"
    else:
        status = "in-flight"
    return status, last_kind, last_ts


_RUNS_LS_STATUSES = ("completed", "in-flight", "aborted")


def cmd_runs_ls(
    argv: Sequence[str],
    *,
    projects_root: Optional[Path] = None,
) -> int:
    parser = argparse.ArgumentParser(prog="astrid runs ls", add_help=True)
    parser.add_argument("--project", default=None, help="optional project slug filter")
    parser.add_argument(
        "--status",
        default=None,
        choices=_RUNS_LS_STATUSES,
        help="filter by terminal status",
    )
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        return int(exc.code or 2)

    if args.project is not None:
        try:
            slug = validate_project_slug(args.project)
        except Exception as exc:
            _print_err(f"runs ls: {exc}")
            return 1
        project_dirs = [project_dir(slug, root=projects_root)]
    else:
        root = resolve_projects_root(projects_root)
        if not root.is_dir():
            return 0
        project_dirs = sorted(p for p in root.iterdir() if p.is_dir())

    rows: list[tuple[str, str, str, str, str]] = []
    for proj in project_dirs:
        runs_root = proj / "runs"
        if not runs_root.is_dir():
            continue
        for run_dir in sorted(p for p in runs_root.iterdir() if p.is_dir()):
            status, last_kind, last_ts = _summarize_run_dir(run_dir)
            if args.status is not None and status != args.status:
                continue
            rows.append((proj.name, run_dir.name, status, last_kind, last_ts))

    for slug, run_id, status, last_kind, last_ts in rows:
        print(f"{slug}\t{run_id}\t{status}\t{last_kind}\t{last_ts}")
    return 0


# ---------------------------------------------------------------------------
# cmd_step_retry_fetch
# ---------------------------------------------------------------------------


def cmd_step_retry_fetch(
    argv: Sequence[str],
    *,
    projects_root: Optional[Path] = None,
) -> int:
    """Retry artifact fetch for a step in ``awaiting_fetch`` state."""
    from astrid.core.adapter.remote_artifact_fetch import fetch_artifacts
    from astrid.core.task.plan_verbs import apply_mutations
    from astrid.core.task.plan import iter_steps_with_path

    parser = argparse.ArgumentParser(prog="astrid step retry-fetch", add_help=True)
    parser.add_argument("step_id", help="step id (e.g. transcribe, render)")
    parser.add_argument("--run", default=None, dest="run_id", help="run id")
    parser.add_argument("--project", default=None, help="project slug")
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        return int(exc.code or 2)

    if args.project is not None:
        try:
            slug = validate_project_slug(args.project)
        except Exception as exc:
            _print_err(f"step retry-fetch: {exc}")
            return 1
    else:
        _print_err("step retry-fetch: --project is required")
        return 1

    if args.run_id is not None:
        try:
            run_id = validate_run_id(args.run_id)
        except Exception as exc:
            _print_err(f"step retry-fetch: --run {exc}")
            return 1
    else:
        current = read_current_run(slug, root=projects_root)
        if current is None:
            _print_err(
                f"step retry-fetch: no active run for project {slug!r} "
                f"and --run not specified"
            )
            return 1
        run_id = current

    proj_root = project_dir(slug, root=projects_root)
    run_dir = proj_root / "runs" / run_id
    if not run_dir.is_dir():
        _print_err(
            f"step retry-fetch: run {run_id!r} not found in project {slug!r}"
        )
        return 1

    events_path = run_dir / "events.jsonl"
    if not events_path.is_file():
        _print_err(
            f"step retry-fetch: no events.jsonl for run {run_id!r}"
        )
        return 1

    events = read_events(events_path)
    if not events:
        _print_err(
            f"step retry-fetch: empty events log for run {run_id!r}"
        )
        return 1

    step_id = args.step_id
    latest_event = _latest_event_for_step(events, step_id)
    if latest_event is None:
        _print_err(
            f"step retry-fetch: no events found for step {step_id!r} "
            f"in run {run_id!r}"
        )
        return 1

    latest_kind = latest_event.get("kind")

    if latest_kind == "step_completed":
        _print_err(
            f"step retry-fetch: step {step_id!r} is already completed"
        )
        return 0

    if latest_kind == "step_failed":
        _print_err(
            f"step retry-fetch: step {step_id!r} is failed, not awaiting_fetch"
        )
        return 1

    if latest_kind != "step_awaiting_fetch":
        _print_err(
            f"step retry-fetch: step {step_id!r} is in state "
            f"{latest_kind!r}, expected awaiting_fetch"
        )
        return 1

    plan_path = proj_root / "plan.json"
    if not plan_path.is_file():
        _print_err(
            f"step retry-fetch: plan.json not found for project {slug!r}"
        )
        return 1

    plan = load_plan(plan_path)
    effective = apply_mutations(plan, events)

    target_step: Step | None = None
    target_path: tuple[str, ...] = ()
    for path_tuple, s in iter_steps_with_path(effective):
        if s.id == step_id and target_step is None:
            target_step = s
            target_path = path_tuple

    if target_step is None:
        _print_err(
            f"step retry-fetch: step {step_id!r} not found in effective plan"
        )
        return 1

    step_version = target_step.version

    from astrid.core.adapter import RunContext

    run_ctx = RunContext(
        slug=slug,
        run_id=run_id,
        project_root=proj_root,
        plan_step_path=target_path,
        step_version=step_version,
    )

    fetch_result = fetch_artifacts(target_step, run_ctx)

    if fetch_result.status == "completed":
        path_str = STEP_PATH_SEP.join(target_path)
        append_event(
            events_path,
            make_step_completed_event(
                path_str,
                0,
                adapter="remote-artifact",
            ),
        )
        print(f"step {step_id}: all artifacts fetched")

        events_after = read_events(events_path)
        plan_after = load_plan(plan_path)
        if _run_is_complete(plan_after, events_after):
            append_event(events_path, make_run_completed_event(run_id))
            print(f"run {run_id}: completed")
        return 0

    if fetch_result.status == "awaiting_fetch":
        path_str = STEP_PATH_SEP.join(target_path)
        append_event(
            events_path,
            make_step_awaiting_fetch_event(
                path_str,
                missing=list(fetch_result.missing),
                mismatched=list(fetch_result.mismatched),
                reason=fetch_result.reason,
                adapter="remote-artifact",
            ),
        )
        _print_err(
            f"step {step_id}: still awaiting_fetch: "
            f"missing={fetch_result.missing}, mismatched={fetch_result.mismatched}"
        )
        return 1

    _print_err(f"step retry-fetch: fetch failed: {fetch_result.reason}")
    return 1


def _latest_event_for_step(
    events: list[dict[str, Any]],
    step_id: str,
) -> dict[str, Any] | None:
    """Return the latest event whose leaf step id matches *step_id*."""
    latest: dict[str, Any] | None = None
    for ev in events:
        if not isinstance(ev, dict):
            continue
        path_list = ev.get("plan_step_path")
        if isinstance(path_list, list) and path_list and path_list[-1] == step_id:
            latest = ev
    return latest


from astrid.core.task.lifecycle_ack import cmd_ack  # noqa: E402
from astrid.core.task.lifecycle_skip import cmd_skip  # noqa: E402

__all__ = [
    "cmd_abort",
    "cmd_ack",
    "cmd_next",
    "cmd_runs_ls",
    "cmd_skip",
    "cmd_start",
    "cmd_status",
    "cmd_step_retry_fetch",
]
