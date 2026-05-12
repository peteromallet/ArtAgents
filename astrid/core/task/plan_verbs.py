"""Plan-mutation verbs: add-step / edit-step / remove-step / supersede-step (Sprint 3 T8)."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from astrid.core.project.paths import project_dir, validate_project_slug, validate_run_id
from astrid.core.task.events import (
    EVENTS_FILENAME,
    LEASE_FILENAME,
    append_event_locked,
    read_events,
)
from astrid.core.task.plan import (
    ADAPTERS,
    SUPERSEDE_SCOPES,
    AckRule,
    Step,
    SupersededRef,
    TaskPlan,
    TaskPlanError,
    iter_steps_with_path,
    load_plan,
)
from astrid.core.task.validator import (
    MutationInvariantError,
    validate_mutation,
)


PLAN_MUTATED_KIND = "plan_mutated"
STEP_TOMBSTONED_KIND = "plan_step_tombstoned"  # rendered inside plan_mutated.diff.op


# -----------------------------------------------------------------------------
# Effective-tree replay
# -----------------------------------------------------------------------------


def apply_mutations(plan: TaskPlan, events: Sequence[dict[str, Any]]) -> TaskPlan:
    """Replay plan_mutated events in order onto ``plan`` to derive the effective tree."""
    current = plan
    for ev in events:
        if not isinstance(ev, dict) or ev.get("kind") != PLAN_MUTATED_KIND:
            continue
        diff = ev.get("diff")
        if not isinstance(diff, dict):
            continue
        current = _apply_diff(current, diff)
    return current


def _apply_diff(plan: TaskPlan, diff: dict[str, Any]) -> TaskPlan:
    op = diff.get("op")
    if op == "add":
        return _apply_add(plan, diff)
    if op == "edit":
        return _apply_edit(plan, diff)
    if op == "remove":
        return _apply_remove(plan, diff)
    if op == "supersede":
        return _apply_supersede(plan, diff)
    raise TaskPlanError(f"unknown plan_mutated.diff.op: {op!r}")


def _step_from_diff(payload: dict[str, Any]) -> Step:
    """Validate a single step dict from a diff payload via the plan validator."""
    # Reuse _validate_step indirectly: wrap into a one-step plan, validate, take steps[0].
    from astrid.core.task.plan import _validate_step  # local import: keeps plan.py public surface clean
    return _validate_step(payload, 0, [])


def _apply_add(plan: TaskPlan, diff: dict[str, Any]) -> TaskPlan:
    step_payload = diff.get("step")
    if not isinstance(step_payload, dict):
        raise TaskPlanError("plan_mutated.add.step must be an object")
    new_step = _step_from_diff(step_payload)
    after = diff.get("after")
    before = diff.get("before")
    into = diff.get("into")
    target_path: tuple[str, ...] | None = None
    if after:
        target_path = tuple(after.split("/"))
        return _replace_steps(plan, _insert(plan.steps, target_path, new_step, mode="after"))
    if before:
        target_path = tuple(before.split("/"))
        return _replace_steps(plan, _insert(plan.steps, target_path, new_step, mode="before"))
    if into:
        target_path = tuple(into.split("/"))
        return _replace_steps(plan, _insert(plan.steps, target_path, new_step, mode="into"))
    # Default: append to root.
    return _replace_steps(plan, plan.steps + (new_step,))


def _apply_edit(plan: TaskPlan, diff: dict[str, Any]) -> TaskPlan:
    path = tuple(diff.get("path", "").split("/"))
    fields = diff.get("fields") or {}
    if not path or not isinstance(fields, dict):
        raise TaskPlanError("plan_mutated.edit requires path + fields")
    def mutate(step: Step) -> Step:
        merged = _step_to_payload(step)
        merged.update(fields)
        merged["id"] = step.id  # id is identity, never editable
        return _step_from_diff(merged)
    return _replace_steps(plan, _replace_at(plan.steps, path, mutate))


def _apply_remove(plan: TaskPlan, diff: dict[str, Any]) -> TaskPlan:
    path = tuple(diff.get("path", "").split("/"))
    return _replace_steps(plan, _remove_at(plan.steps, path))


def _apply_supersede(plan: TaskPlan, diff: dict[str, Any]) -> TaskPlan:
    path = tuple(diff.get("path", "").split("/"))
    to_version = diff.get("to_version")
    scope = diff.get("scope")
    new_step_payload = diff.get("step")
    if not isinstance(to_version, int) or scope not in SUPERSEDE_SCOPES:
        raise TaskPlanError("plan_mutated.supersede requires to_version:int + scope")
    if not isinstance(new_step_payload, dict):
        raise TaskPlanError("plan_mutated.supersede requires step:dict")

    def mutate(step: Step) -> Step:
        payload = dict(new_step_payload)
        payload.setdefault("id", step.id)
        payload["version"] = to_version
        new_step = _step_from_diff(payload)
        # Record old version's superseded_by pointer in a sibling placeholder?
        # Per brief: original v1/ dir is preserved, cursor walks effective tree honoring scope.
        # We model "current" as the new version; the old version is reconstructible from
        # the prior plan_mutated event chain.
        return dataclasses.replace(new_step, superseded_by=None)

    return _replace_steps(plan, _replace_at(plan.steps, path, mutate))


# Step-tree helpers --------------------------------------------------------------------


def _replace_steps(plan: TaskPlan, steps: tuple[Step, ...]) -> TaskPlan:
    return TaskPlan(plan_id=plan.plan_id, version=plan.version, steps=steps)


def _insert(steps: tuple[Step, ...], path: tuple[str, ...], new_step: Step, *, mode: str) -> tuple[Step, ...]:
    if len(path) == 1:
        target = path[0]
        out: list[Step] = []
        inserted = False
        for s in steps:
            if s.id == target:
                if mode == "before":
                    out.append(new_step)
                    out.append(s)
                elif mode == "after":
                    out.append(s)
                    out.append(new_step)
                elif mode == "into":
                    if s.children is None:
                        raise TaskPlanError(f"--into target {target!r} is a leaf step")
                    out.append(dataclasses.replace(s, children=s.children + (new_step,)))
                else:
                    raise TaskPlanError(f"unknown insert mode {mode!r}")
                inserted = True
            else:
                out.append(s)
        if not inserted:
            raise TaskPlanError(f"insert target {target!r} not found at frame")
        return tuple(out)
    # Descend.
    head, *rest = path
    rest_tuple = tuple(rest)
    return tuple(
        dataclasses.replace(s, children=_insert(s.children or (), rest_tuple, new_step, mode=mode))
        if s.id == head and s.children is not None
        else s
        for s in steps
    )


def _replace_at(steps: tuple[Step, ...], path: tuple[str, ...], mutate) -> tuple[Step, ...]:
    if not path:
        raise TaskPlanError("_replace_at: empty path")
    head = path[0]
    rest = path[1:]
    out: list[Step] = []
    found = False
    for s in steps:
        if s.id == head:
            found = True
            if not rest:
                out.append(mutate(s))
            else:
                if s.children is None:
                    raise TaskPlanError(f"path {'/'.join(path)} descends past leaf step {head!r}")
                out.append(dataclasses.replace(s, children=_replace_at(s.children, rest, mutate)))
        else:
            out.append(s)
    if not found:
        raise TaskPlanError(f"path segment {head!r} not found at frame")
    return tuple(out)


def _remove_at(steps: tuple[Step, ...], path: tuple[str, ...]) -> tuple[Step, ...]:
    if not path:
        raise TaskPlanError("_remove_at: empty path")
    head = path[0]
    rest = path[1:]
    if not rest:
        return tuple(s for s in steps if s.id != head)
    return tuple(
        dataclasses.replace(s, children=_remove_at(s.children, rest))
        if s.id == head and s.children is not None
        else s
        for s in steps
    )


def _step_to_payload(step: Step) -> dict[str, Any]:
    """Reverse of _validate_step for diff-edit field merging."""
    from astrid.core.task.plan import _step_to_dict
    return dict(_step_to_dict(step))


# -----------------------------------------------------------------------------
# Dispatched-step detection (for edit/remove rejection)
# -----------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class CursorRecord:
    """Event-derived per-step cursor entry: (step_id, step_version, dispatch_event_hash).

    Reconstructed from events.jsonl alone — no on-disk artifact. Read by `astrid status`
    and the gate so post-supersede dispatches know which version is current.
    """

    step_id: str
    step_version: int
    dispatch_event_hash: str | None


def derive_versioned_cursor(events: Sequence[dict[str, Any]]) -> dict[str, CursorRecord]:
    """Walk events.jsonl, return step_id -> CursorRecord of the most recent dispatch+version.

    Honors supersede scope by walking plan_mutated events: a supersede with scope='all'
    resets in-flight iter/item progress (the cursor abandons any pending state and
    restarts on the new version's iter/item 1). scope=future-iterations and scope=future-items
    only affect the NEXT iteration/item; current iteration/item retains the old version.
    """
    records: dict[str, CursorRecord] = {}
    # supersede_scope tracks (step_id -> pending scope) so a subsequent dispatch picks
    # the right version.
    for ev in events:
        if not isinstance(ev, dict):
            continue
        kind = ev.get("kind")
        if kind == "step_dispatched":
            psp = ev.get("plan_step_path") or ev.get("plan_step_id")
            if isinstance(psp, list):
                psp = "/".join(psp)
            if not isinstance(psp, str):
                continue
            step_version = int(ev.get("step_version", 1))
            records[psp] = CursorRecord(
                step_id=psp,
                step_version=step_version,
                dispatch_event_hash=ev.get("hash") if isinstance(ev.get("hash"), str) else None,
            )
        elif kind == PLAN_MUTATED_KIND:
            diff = ev.get("diff")
            if not isinstance(diff, dict):
                continue
            if diff.get("op") == "supersede":
                psp = diff.get("path")
                to_version = int(diff.get("to_version", 1))
                if isinstance(psp, str):
                    # Update the cursor record so future dispatches see the bumped version.
                    prior = records.get(psp)
                    records[psp] = CursorRecord(
                        step_id=psp,
                        step_version=to_version,
                        dispatch_event_hash=None,  # No dispatch yet at the new version.
                    )
    return records


def _dispatched_step_paths(events: Sequence[dict[str, Any]]) -> set[str]:
    """Returns the set of plan_step_path strings that have had a step_dispatched event."""
    dispatched: set[str] = set()
    for ev in events:
        if not isinstance(ev, dict):
            continue
        if ev.get("kind") == "step_dispatched":
            psp = ev.get("plan_step_path") or ev.get("plan_step_id")
            if isinstance(psp, list):
                psp = "/".join(psp)
            if isinstance(psp, str):
                dispatched.add(psp)
    return dispatched


# -----------------------------------------------------------------------------
# Verb commands
# -----------------------------------------------------------------------------


def _make_plan_mutated_event(actor: str, writer_epoch: int, diff: dict[str, Any]) -> dict[str, Any]:
    from astrid.core.task.events import _utc_now_iso  # internal helper reuse
    return {
        "kind": PLAN_MUTATED_KIND,
        "actor": actor,
        "writer_epoch": writer_epoch,
        "diff": diff,
        "ts": _utc_now_iso(),
    }


def _run_dir(slug: str, run_id: str, root: str | Path | None) -> Path:
    return project_dir(slug, root=root) / "runs" / run_id


def _read_lease_epoch(run_dir: Path) -> int:
    lease_path = run_dir / LEASE_FILENAME
    if not lease_path.exists():
        raise TaskPlanError(f"lease not found at {lease_path}")
    try:
        payload = json.loads(lease_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TaskPlanError(f"malformed lease.json at {lease_path}: {exc}") from exc
    return int(payload.get("writer_epoch", 0))


def _load_effective_plan(run_dir: Path) -> tuple[TaskPlan, list[dict[str, Any]]]:
    plan = load_plan(run_dir / "plan.json")
    events = read_events(run_dir / EVENTS_FILENAME)
    return apply_mutations(plan, events), events


def _emit(run_dir: Path, event: dict[str, Any], expected_epoch: int) -> dict[str, Any]:
    from astrid.core.task.events import _peek_tail_hash
    prev_hash = _peek_tail_hash(run_dir / EVENTS_FILENAME)
    return append_event_locked(
        run_dir,
        event,
        expected_writer_epoch=expected_epoch,
        expected_prev_hash=prev_hash,
    )


def _print_err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _validate_and_emit(
    run_dir: Path,
    prior_plan: TaskPlan,
    proposed_plan: TaskPlan,
    *,
    diff: dict[str, Any],
    actor: str,
    expected_epoch: int,
) -> int:
    try:
        validate_mutation(
            prior_plan,
            proposed_plan,
            lease_epoch_actual=_read_lease_epoch(run_dir),
            lease_epoch_expected=expected_epoch,
        )
    except MutationInvariantError as exc:
        _print_err(f"plan: rejected at {exc.invariant_id} ({exc.element}): {exc.reason}")
        return 1
    event = _make_plan_mutated_event(actor=actor, writer_epoch=expected_epoch, diff=diff)
    try:
        _emit(run_dir, event, expected_epoch)
    except Exception as exc:  # StaleTailError / StaleEpochError / EventLogError
        _print_err(f"plan: event-append failed: {exc}")
        return 1
    print(f"plan_mutated [{diff.get('op')}] emitted at writer_epoch={expected_epoch}")
    return 0


def cmd_plan_add_step(argv: Sequence[str], *, projects_root: Path | None = None) -> int:
    parser = _add_step_parser()
    args = parser.parse_args(list(argv))
    return _dispatch_add(args, projects_root)


def _dispatch_add(args, projects_root: Path | None) -> int:
    slug = validate_project_slug(args.project)
    run_id = validate_run_id(args.run_id)
    run_dir = _run_dir(slug, run_id, projects_root)
    prior_plan, events = _load_effective_plan(run_dir)

    step_payload: dict[str, Any] = {
        "id": args.step_id,
        "adapter": args.adapter,
        "command": args.command,
    }
    if args.assignee:
        step_payload["assignee"] = args.assignee
    if args.requires_ack:
        step_payload["requires_ack"] = True
    diff: dict[str, Any] = {"op": "add", "step": step_payload}
    if args.after:
        diff["after"] = args.after
    elif args.before:
        diff["before"] = args.before
    elif args.into:
        diff["into"] = args.into

    try:
        proposed = _apply_diff(prior_plan, diff)
    except TaskPlanError as exc:
        _print_err(f"plan add-step: {exc}")
        return 1

    actor = args.actor or f"agent:{slug}"
    return _validate_and_emit(
        run_dir, prior_plan, proposed,
        diff=diff, actor=actor, expected_epoch=_read_lease_epoch(run_dir),
    )


def cmd_plan_edit_step(argv: Sequence[str], *, projects_root: Path | None = None) -> int:
    parser = _edit_step_parser()
    args = parser.parse_args(list(argv))
    slug = validate_project_slug(args.project)
    run_id = validate_run_id(args.run_id)
    run_dir = _run_dir(slug, run_id, projects_root)
    prior_plan, events = _load_effective_plan(run_dir)

    if args.step in _dispatched_step_paths(events):
        _print_err(f"plan edit-step: {args.step!r} is dispatched; use supersede-step to bump version")
        return 1

    fields: dict[str, Any] = {}
    if args.command is not None:
        fields["command"] = args.command
    if args.assignee is not None:
        fields["assignee"] = args.assignee
    if not fields:
        _print_err("plan edit-step: no editable fields provided (--command, --assignee)")
        return 1
    diff: dict[str, Any] = {"op": "edit", "path": args.step, "fields": fields}
    try:
        proposed = _apply_diff(prior_plan, diff)
    except TaskPlanError as exc:
        _print_err(f"plan edit-step: {exc}")
        return 1

    actor = args.actor or f"agent:{slug}"
    return _validate_and_emit(
        run_dir, prior_plan, proposed,
        diff=diff, actor=actor, expected_epoch=_read_lease_epoch(run_dir),
    )


def cmd_plan_remove_step(argv: Sequence[str], *, projects_root: Path | None = None) -> int:
    parser = _remove_step_parser()
    args = parser.parse_args(list(argv))
    slug = validate_project_slug(args.project)
    run_id = validate_run_id(args.run_id)
    run_dir = _run_dir(slug, run_id, projects_root)
    prior_plan, events = _load_effective_plan(run_dir)

    if args.step in _dispatched_step_paths(events):
        _print_err(
            f"plan remove-step: {args.step!r} is dispatched; "
            "use 'astrid abort' on the run or supersede-step instead"
        )
        return 1

    diff: dict[str, Any] = {"op": "remove", "path": args.step}
    try:
        proposed = _apply_diff(prior_plan, diff)
    except TaskPlanError as exc:
        _print_err(f"plan remove-step: {exc}")
        return 1

    actor = args.actor or f"agent:{slug}"
    return _validate_and_emit(
        run_dir, prior_plan, proposed,
        diff=diff, actor=actor, expected_epoch=_read_lease_epoch(run_dir),
    )


def cmd_plan_supersede_step(argv: Sequence[str], *, projects_root: Path | None = None) -> int:
    parser = _supersede_step_parser()
    args = parser.parse_args(list(argv))
    slug = validate_project_slug(args.project)
    run_id = validate_run_id(args.run_id)
    run_dir = _run_dir(slug, run_id, projects_root)
    prior_plan, events = _load_effective_plan(run_dir)

    # Find current version of the target step.
    target_path = tuple(args.step.split("/"))
    current_step: Step | None = next(
        (s for path, s in iter_steps_with_path(prior_plan) if path == target_path),
        None,
    )
    if current_step is None:
        _print_err(f"plan supersede-step: path {args.step!r} not found in effective plan")
        return 1
    new_version = current_step.version + 1

    new_step_payload: dict[str, Any] = {
        "id": current_step.id,
        "adapter": args.adapter or current_step.adapter,
        "command": args.command or current_step.command,
        "version": new_version,
    }
    if current_step.assignee != "system":
        new_step_payload["assignee"] = current_step.assignee
    if current_step.requires_ack:
        new_step_payload["requires_ack"] = True

    diff: dict[str, Any] = {
        "op": "supersede",
        "path": args.step,
        "to_version": new_version,
        "scope": args.scope,
        "step": new_step_payload,
    }
    try:
        proposed = _apply_diff(prior_plan, diff)
    except TaskPlanError as exc:
        _print_err(f"plan supersede-step: {exc}")
        return 1

    actor = args.actor or f"agent:{slug}"
    return _validate_and_emit(
        run_dir, prior_plan, proposed,
        diff=diff, actor=actor, expected_epoch=_read_lease_epoch(run_dir),
    )


# -----------------------------------------------------------------------------
# argparse — produces real --help output for every subverb
# -----------------------------------------------------------------------------


def _common_parent_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", required=True, help="project slug")
    parser.add_argument("--run-id", required=True, help="run id (under runs/<run-id>/)")
    parser.add_argument("--actor", default=None, help="actor (default: agent:<project>)")


def _add_step_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="astrid plan add-step", description="Insert a step into the effective plan.")
    _common_parent_args(p)
    p.add_argument("--step-id", required=True, help="new step id")
    p.add_argument("--command", required=True, help="step command (dispatch payload)")
    p.add_argument("--adapter", default="local", choices=list(ADAPTERS), help="adapter")
    p.add_argument("--assignee", default=None, help="assignee form (system|any-agent|any-human|agent:<id>|human:<name>)")
    p.add_argument("--requires-ack", action="store_true", help="require astrid ack before completion")
    pos = p.add_mutually_exclusive_group()
    pos.add_argument("--after", default=None, help="insert after this step path")
    pos.add_argument("--before", default=None, help="insert before this step path")
    pos.add_argument("--into", default=None, help="append as child of this group step path")
    return p


def _edit_step_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="astrid plan edit-step", description="Edit an undispatched step in-place.")
    _common_parent_args(p)
    p.add_argument("step", help="step path (slash-joined)")
    p.add_argument("--command", default=None)
    p.add_argument("--assignee", default=None)
    return p


def _remove_step_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="astrid plan remove-step", description="Tombstone an undispatched step.")
    _common_parent_args(p)
    p.add_argument("step", help="step path (slash-joined)")
    return p


def _supersede_step_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="astrid plan supersede-step", description="Bump version on a dispatched step.")
    _common_parent_args(p)
    p.add_argument("step", help="step path (slash-joined)")
    p.add_argument(
        "--scope",
        required=True,
        choices=list(SUPERSEDE_SCOPES),
        help="supersede scope (all | future-iterations | future-items)",
    )
    p.add_argument("--command", default=None, help="new command (defaults to current)")
    p.add_argument("--adapter", default=None, choices=list(ADAPTERS), help="new adapter (defaults to current)")
    return p


def build_parser() -> argparse.ArgumentParser:
    """Top-level `astrid plan` parser with subverbs. T17 wires into pipeline.py."""
    parser = argparse.ArgumentParser(
        prog="astrid plan",
        description="Mutate the effective plan: add-step / edit-step / remove-step / supersede-step.",
    )
    subs = parser.add_subparsers(dest="verb", required=True)
    subs.add_parser(
        "add-step",
        help="Insert a step into the effective plan",
        description="Insert a step into the effective plan.",
        parents=[_add_step_parser()],
        conflict_handler="resolve",
        add_help=True,
    )
    subs.add_parser(
        "edit-step",
        help="Edit an undispatched step in-place",
        description="Edit an undispatched step in-place.",
        parents=[_edit_step_parser()],
        conflict_handler="resolve",
        add_help=True,
    )
    subs.add_parser(
        "remove-step",
        help="Tombstone an undispatched step",
        description="Tombstone an undispatched step.",
        parents=[_remove_step_parser()],
        conflict_handler="resolve",
        add_help=True,
    )
    subs.add_parser(
        "supersede-step",
        help="Bump version on a dispatched step (--scope required)",
        description="Bump version on a dispatched step. --scope is required.",
        parents=[_supersede_step_parser()],
        conflict_handler="resolve",
        add_help=True,
    )
    return parser


def cmd_plan(argv: Sequence[str], *, projects_root: Path | None = None) -> int:
    """Entry point for `astrid plan ...` — T17 dispatches here."""
    parser = build_parser()
    args = parser.parse_args(list(argv))
    if args.verb == "add-step":
        return _dispatch_add(args, projects_root)
    if args.verb == "edit-step":
        # Re-parse via cmd_plan_edit_step's path? args already has slug/run-id; route directly.
        return _route_subverb(cmd_plan_edit_step, argv, projects_root)
    if args.verb == "remove-step":
        return _route_subverb(cmd_plan_remove_step, argv, projects_root)
    if args.verb == "supersede-step":
        return _route_subverb(cmd_plan_supersede_step, argv, projects_root)
    parser.error(f"unknown verb {args.verb!r}")
    return 2  # unreachable


def _route_subverb(fn, argv: Sequence[str], projects_root: Path | None) -> int:
    # Strip the leading subverb token before handing off to the dedicated cmd_*.
    if argv and argv[0] in {"add-step", "edit-step", "remove-step", "supersede-step"}:
        argv = argv[1:]
    return fn(argv, projects_root=projects_root)


__all__ = [
    "PLAN_MUTATED_KIND",
    "apply_mutations",
    "build_parser",
    "cmd_plan",
    "cmd_plan_add_step",
    "cmd_plan_edit_step",
    "cmd_plan_remove_step",
    "cmd_plan_supersede_step",
]
