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

from artagents.core.project.jsonio import write_json_atomic
from artagents.core.project.paths import (
    project_dir,
    resolve_projects_root,
    validate_project_slug,
    validate_run_id,
)
from artagents.core.task.active_run import (
    clear_active_run,
    read_active_run,
    write_active_run,
)
from artagents.core.task.env import task_actor_env
from artagents.core.task.events import (
    append_event,
    make_run_aborted_event,
    make_run_started_event,
    read_events,
)
from artagents.core.task.gate import peek_current_step
from artagents.core.task.plan import (
    STEP_PATH_SEP,
    AttestedStep,
    CodeStep,
    NestedStep,
    RepeatForEach,
    compute_plan_hash,
    load_plan,
    step_dir_for_path,
)
from artagents.core.task.preamble import PROHIBITION_PREAMBLE


_AGENT_MD_TEMPLATE = """{preamble}

QUALIFIED ORCHESTRATOR: {qualified_id}
RUN ID: {run_id}

RECOVERY COMMANDS
- See next legal action:    artagents next --project {slug}
- Acknowledge attested:     artagents ack <step> --project {slug} --decision approve [--agent <id> | --actor <name>]
- View run state:           artagents status --project {slug}
- End the run:              artagents abort --project {slug}

STOP HOOK
- The `artagents hook stop` command is the Claude Code Stop-hook entry point.
  When wired into .claude/settings.json (see docs/HOOKS.md) it re-injects this
  preamble and the current step on every Stop boundary so the rules above
  stay live for the entire run. The hook is a silent no-op outside task mode.
"""


def _print_err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _resolve_packs_root(packs_root: Optional[Path]) -> Path:
    if packs_root is not None:
        return Path(packs_root)
    from artagents.orchestrate.compile import DEFAULT_PACKS_ROOT
    return DEFAULT_PACKS_ROOT


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
    parser = argparse.ArgumentParser(prog="artagents start", add_help=True)
    parser.add_argument("orchestrator_id", help="qualified id <pack>.<name>")
    parser.add_argument("--project", required=True, help="project slug")
    parser.add_argument("--name", default=None, help="optional run id (slug-validated)")
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        return int(exc.code or 2)

    try:
        slug = validate_project_slug(args.project)
    except Exception as exc:
        _print_err(f"start: {exc}")
        return 1

    try:
        pack, name = _qualified_split(args.orchestrator_id)
    except ValueError as exc:
        _print_err(f"start: {exc}")
        return 1

    if read_active_run(slug, root=projects_root) is not None:
        _print_err(
            f"start: active run already exists for project {slug!r}; "
            f"recovery: artagents abort --project {slug}"
        )
        return 1

    packs = _resolve_packs_root(packs_root)
    build_path = packs / pack / "build" / f"{name}.json"
    if not build_path.is_file():
        _print_err(
            f"start: compiled plan not found at {build_path}; "
            f"recovery: artagents author compile {args.orchestrator_id}"
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

    write_active_run(slug, run_id=run_id, plan_hash=plan_hash, root=projects_root)

    events_path = run_dir / "events.jsonl"
    actor = task_actor_env()
    append_event(events_path, make_run_started_event(run_id, plan_hash, actor=actor))

    agent_md = _AGENT_MD_TEMPLATE.format(
        preamble=PROHIBITION_PREAMBLE,
        qualified_id=args.orchestrator_id,
        run_id=run_id,
        slug=slug,
    )
    (run_dir / "AGENT.md").write_text(agent_md, encoding="utf-8")

    print(f"started {args.orchestrator_id}")
    print(f"  project:   {slug}")
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
    parser = argparse.ArgumentParser(prog="artagents abort", add_help=True)
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

    active_run = read_active_run(slug, root=projects_root)
    if active_run is None:
        # Idempotent — Phase 6 Stop-hook may invoke abort defensively.
        return 0

    run_id = active_run["run_id"]
    events_path = (
        project_dir(slug, root=projects_root) / "runs" / run_id / "events.jsonl"
    )
    append_event(events_path, make_run_aborted_event(run_id, reason=args.reason))
    clear_active_run(slug, root=projects_root)
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
    parser = argparse.ArgumentParser(prog="artagents status", add_help=True)
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
            f"recovery: artagents start <orchestrator-id> --project {slug}"
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
        kind = "code" if isinstance(peek.step, CodeStep) else (
            "attested" if isinstance(peek.step, AttestedStep) else "nested"
        )
        suffix = ""
        if peek.iteration is not None:
            suffix += f"  iter={peek.iteration}"
        if peek.item_id is not None:
            suffix += f"  item={peek.item_id}"
        print(f"current:   {path_str} [{kind}]{suffix}")
        if peek.step.produces:
            names = ", ".join(p.name for p in peek.step.produces)
            print(f"produces:  {names}")

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
        f"artagents ack {path_str} --project {slug} --decision approve "
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
        if match is None or not isinstance(match, NestedStep):
            return None
        steps = match.plan.steps
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
    parser = argparse.ArgumentParser(prog="artagents next", add_help=True)
    parser.add_argument("--project", required=True, help="project slug")
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
        print("run complete")
        print(f"recovery: artagents abort --project {slug}")
        return 0

    path_str = STEP_PATH_SEP.join(peek.path_tuple)

    if isinstance(peek.step, CodeStep):
        print(f"run: {peek.step.command}")
        print(
            "(rerun the same command if it failed; the gate detects re-entry "
            "and skips a duplicate step_dispatched event.)"
        )
    elif isinstance(peek.step, AttestedStep):
        print(peek.step.instructions)
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
                ack_kind=peek.step.ack.kind,
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

    Per FLAG-P5-006: only ``aborted`` vs ``in-progress`` are reliably
    distinguishable in V1. A naturally completed plan still leaves
    ``active_run.json`` in place, so the "complete" bucket is mostly
    unobservable.
    """
    events_path = run_dir / "events.jsonl"
    if not events_path.is_file():
        return "in-progress", "", ""
    events = read_events(events_path)
    if not events:
        return "in-progress", "", ""
    last = events[-1]
    last_kind = str(last.get("kind", ""))
    last_ts = str(last.get("ts", ""))
    status = "aborted" if last_kind == "run_aborted" else "in-progress"
    return status, last_kind, last_ts


def cmd_runs_ls(
    argv: Sequence[str],
    *,
    projects_root: Optional[Path] = None,
) -> int:
    parser = argparse.ArgumentParser(prog="artagents runs ls", add_help=True)
    parser.add_argument("--project", default=None, help="optional project slug filter")
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
            rows.append((proj.name, run_dir.name, status, last_kind, last_ts))

    for slug, run_id, status, last_kind, last_ts in rows:
        print(f"{slug}\t{run_id}\t{status}\t{last_kind}\t{last_ts}")
    return 0


from artagents.core.task.lifecycle_ack import cmd_ack  # noqa: E402

__all__ = [
    "cmd_abort",
    "cmd_ack",
    "cmd_next",
    "cmd_runs_ls",
    "cmd_start",
    "cmd_status",
]
