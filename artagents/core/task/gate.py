"""Task-run dispatch gate.

Phase 2 attested/nested handling is kernel-only; Phase 5 will add the
``artagents ack`` / ``artagents next`` lifecycle verbs that drive the
``record_step_attested`` / ``record_nested_entered`` / ``record_nested_exited``
helpers exposed for symmetry below. The gate itself emits ``step_attested``,
``nested_entered``, and ``nested_exited`` events inline; the public helpers
have zero callers in Phase 2 (FLAG-007).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from artagents.core.project.paths import project_dir
from artagents.core.task.active_run import read_active_run
from artagents.core.task.env import (
    apply_task_run_env,
    is_in_task_run,
    task_actor_env,
)
from artagents.core.task.events import (
    append_event,
    canonical_event_json,
    make_cursor_rewind_event,
    make_for_each_expanded_event,
    make_item_attested_event,
    make_item_started_event,
    make_iteration_exhausted_event,
    make_iteration_failed_event,
    make_iteration_started_event,
    make_nested_entered_event,
    make_nested_exited_event,
    make_produces_check_failed_event,
    make_produces_check_passed_event,
    make_step_attested_event,
    make_step_completed_event,
    make_step_dispatched_event,
    read_events,
    verify_chain,
)
from artagents.core.task.cas import intern, link_into_produces
from artagents.core.task.plan import (
    STEP_PATH_SEP,
    AckRule,
    AttestedStep,
    CodeStep,
    NestedStep,
    ProducesEntry,
    RepeatForEach,
    RepeatUntil,
    TaskPlan,
    compute_plan_hash,
    load_plan,
    parse_from_ref,
    step_dir_for_path,
)


ITERATE_FEEDBACK_PREFIX = "iterate_feedback="


class TaskRunGateError(RuntimeError):
    """Raised when task-mode dispatch is rejected."""

    def __init__(self, reason: str, recovery: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.recovery = recovery


@dataclass(frozen=True)
class GateDecision:
    active: bool
    run_id: str | None = None
    plan_step_id: str | None = None
    events_path: Path | None = None
    reentry: bool = False
    step_kind: str | None = None
    slug: str | None = None
    plan_step_path: tuple[str, ...] = ()
    produces: tuple[ProducesEntry, ...] = ()
    project_root: Path | None = None
    iteration: int | None = None
    item_id: str | None = None


@dataclass(frozen=True)
class AttestedArgs:
    agent: str | None
    actor: str | None
    evidence: tuple[str, ...]
    item: str | None = None


@dataclass
class _Frame:
    plan: TaskPlan
    path_prefix: tuple[str, ...]
    child_index: int = 0
    iteration: int | None = None
    item_id: str | None = None
    repeat_step_id: str | None = None


@dataclass
class CursorPath:
    frames: list[_Frame] = field(default_factory=list)
    for_each_progress: dict[str, dict[str, Any]] = field(default_factory=dict)
    pinned_failure: tuple[str, str] | None = None  # (reason, host_path) for iteration_exhausted=fail

    @property
    def at_root_done(self) -> bool:
        return len(self.frames) == 1 and self.frames[-1].child_index >= len(self.frames[-1].plan.steps)

    @property
    def top_exhausted(self) -> bool:
        top = self.frames[-1]
        return top.child_index >= len(top.plan.steps)


def derive_cursor(plan: TaskPlan, events: Sequence[dict[str, Any]], *, slug: str = "") -> CursorPath:
    """Replay ``events.jsonl`` left-to-right to reconstruct the path-stack cursor.

    Reconstructible from events alone (supports partial-replay resume):
    ``nested_entered`` pushes, ``nested_exited`` pops + advances parent,
    ``step_completed`` / ``step_attested`` mark a step advance-eligible iff it
    has no produces; otherwise advance is deferred until the contiguous block
    contains a ``produces_check_passed`` for every declared produces name.
    ``produces_check_failed`` / ``cursor_rewind`` clear pending state without
    advancing. ``iteration_started`` pushes an iteration frame; ``iteration_failed``
    pops it without advancing the host. ``for_each_expanded`` records the host's
    item set on the cursor (used as the source of truth — derive_cursor never
    re-reads disk during replay). ``item_started`` pushes a per-item frame;
    ``item_completed`` / ``item_attested`` pop the item frame and advance the
    host once every item is done. ``step_dispatched`` / ``run_started`` do not
    advance.
    """
    frames: list[_Frame] = [_Frame(plan=plan, path_prefix=(), child_index=0)]
    pending: list[set[str] | None] = [None]
    for_each_progress: dict[str, dict[str, Any]] = {}
    pinned_failure: tuple[str, str] | None = None
    for event in events:
        kind = event.get("kind")
        if kind == "iteration_exhausted":
            on_exhaust = event.get("on_exhaust")
            host_path = _path_str_from_event(event)
            if on_exhaust == "fail":
                pinned_failure = ("repeat.until max_iterations exhausted", host_path)
                continue
            if on_exhaust == "escalate":
                top = frames[-1]
                if top.child_index < len(top.plan.steps):
                    host_step = top.plan.steps[top.child_index]
                    override_plan = TaskPlan(
                        plan_id=f"__exhaust_{host_step.id}",
                        version=1,
                        steps=(_make_exhaust_override_step(slug, host_path),),
                    )
                    frames.append(
                        _Frame(
                            plan=override_plan,
                            path_prefix=top.path_prefix + (host_step.id,),
                            child_index=0,
                            repeat_step_id=host_step.id,
                        )
                    )
                    pending.append(None)
            continue
        if kind == "nested_entered":
            top = frames[-1]
            if top.child_index >= len(top.plan.steps):
                raise TaskRunGateError(
                    reason="nested_entered points past end of frame",
                    recovery="inspect events.jsonl",
                )
            step = top.plan.steps[top.child_index]
            if not isinstance(step, NestedStep):
                raise TaskRunGateError(
                    reason="nested_entered did not land on a NestedStep",
                    recovery="inspect events.jsonl",
                )
            frames.append(
                _Frame(
                    plan=step.plan,
                    path_prefix=top.path_prefix + (step.id,),
                    child_index=0,
                )
            )
            pending.append(None)
        elif kind == "nested_exited":
            if len(frames) <= 1:
                raise TaskRunGateError(
                    reason="nested_exited at root frame",
                    recovery="inspect events.jsonl",
                )
            frames.pop()
            pending.pop()
            frames[-1].child_index += 1
            pending[-1] = None
        elif kind == "iteration_started":
            top = frames[-1]
            if top.child_index >= len(top.plan.steps):
                continue
            host_step = top.plan.steps[top.child_index]
            iteration = int(event.get("iteration", 1))
            frames.append(_make_iteration_frame(host_step, top.path_prefix, iteration))
            pending.append(None)
        elif kind == "iteration_failed":
            if frames[-1].repeat_step_id is None:
                continue
            frames.pop()
            pending.pop()
            pending[-1] = None
        elif kind == "for_each_expanded":
            host_path = _path_str_from_event(event)
            items = tuple(event.get("item_ids") or ())
            for_each_progress.setdefault(host_path, {"items": items, "completed": set()})
            for_each_progress[host_path]["items"] = items
        elif kind == "item_started":
            top = frames[-1]
            if top.child_index >= len(top.plan.steps):
                continue
            host_step = top.plan.steps[top.child_index]
            item_id = event.get("item_id")
            if not isinstance(item_id, str):
                continue
            frames.append(_make_item_frame(host_step, top.path_prefix, item_id))
            pending.append(None)
        elif kind in ("item_completed", "item_attested"):
            host_path = _path_str_from_event(event)
            item_id = event.get("item_id")
            if not isinstance(item_id, str):
                continue
            entry = for_each_progress.setdefault(host_path, {"items": (), "completed": set()})
            entry["completed"].add(item_id)
            if frames[-1].item_id == item_id:
                frames.pop()
                pending.pop()
                pending[-1] = None
            # If all items now completed and the host's parent frame is on top, advance host.
            if entry["items"] and set(entry["items"]) <= entry["completed"]:
                host_segments = host_path.split(STEP_PATH_SEP) if host_path else []
                expected_parent_prefix = tuple(host_segments[:-1])
                if tuple(frames[-1].path_prefix) == expected_parent_prefix:
                    if frames[-1].child_index < len(frames[-1].plan.steps):
                        candidate = frames[-1].plan.steps[frames[-1].child_index]
                        if host_segments and candidate.id == host_segments[-1]:
                            frames[-1].child_index += 1
                            pending[-1] = None
        elif kind in ("step_completed", "step_attested"):
            top = frames[-1]
            if top.child_index >= len(top.plan.steps):
                continue
            step = top.plan.steps[top.child_index]
            produces = getattr(step, "produces", ())
            if not produces:
                top.child_index += 1
                pending[-1] = None
            else:
                pending[-1] = {entry.name for entry in produces}
        elif kind == "produces_check_passed":
            current = pending[-1]
            if current is not None:
                name = event.get("produces_name")
                current.discard(name)
                if not current:
                    frames[-1].child_index += 1
                    pending[-1] = None
        elif kind in ("produces_check_failed", "cursor_rewind"):
            pending[-1] = None
        elif kind == "step_dispatched":
            pending[-1] = None
        # run_started / iteration_exhausted: no-op for cursor
    _finalize_cursor(frames, pending, for_each_progress)
    return CursorPath(frames=frames, for_each_progress=for_each_progress, pinned_failure=pinned_failure)


def _make_iteration_frame(host_step: Any, parent_prefix: tuple[str, ...], iteration: int) -> _Frame:
    body = dataclasses.replace(host_step, repeat=None) if hasattr(host_step, "repeat") else host_step
    body_plan = TaskPlan(plan_id=f"__iter_{host_step.id}_{iteration}", version=1, steps=(body,))
    return _Frame(
        plan=body_plan,
        path_prefix=parent_prefix,
        child_index=0,
        iteration=iteration,
        repeat_step_id=host_step.id,
    )


def _make_item_frame(host_step: Any, parent_prefix: tuple[str, ...], item_id: str) -> _Frame:
    body = dataclasses.replace(host_step, repeat=None) if hasattr(host_step, "repeat") else host_step
    body_plan = TaskPlan(plan_id=f"__item_{host_step.id}_{item_id}", version=1, steps=(body,))
    return _Frame(
        plan=body_plan,
        path_prefix=parent_prefix,
        child_index=0,
        item_id=item_id,
        repeat_step_id=host_step.id,
    )


def _finalize_cursor(
    frames: list[_Frame],
    pending: list[set[str] | None],
    for_each_progress: dict[str, dict[str, Any]],
) -> None:
    """Pop exhausted iteration/item frames after event replay.

    For verifier_passes / approve cases, the iteration frame ends with
    ``produces_check_passed`` coverage or ``step_attested`` (no following
    iteration_failed) — the iter frame's child_index is at end-of-plan.
    Pop it and advance the host. Same for item frames whose item is in
    the for_each_progress.completed set.
    """
    while True:
        top = frames[-1]
        if top.repeat_step_id is None:
            break
        if top.child_index < len(top.plan.steps):
            break
        if top.item_id is not None:
            host_path_segments = top.path_prefix + (top.repeat_step_id,)
            host_path = STEP_PATH_SEP.join(host_path_segments)
            entry = for_each_progress.get(host_path)
            frames.pop()
            pending.pop()
            pending[-1] = None
            if entry is not None and entry["items"] and set(entry["items"]) <= entry["completed"]:
                frames[-1].child_index += 1
                pending[-1] = None
        else:
            frames.pop()
            pending.pop()
            frames[-1].child_index += 1
            pending[-1] = None


def _path_str_from_event(event: dict[str, Any]) -> str:
    path = event.get("plan_step_path")
    if isinstance(path, list):
        return STEP_PATH_SEP.join(str(p) for p in path)
    pid = event.get("plan_step_id")
    return pid if isinstance(pid, str) else ""


def _auto_traverse_to_leaf(
    *,
    slug: str,
    cursor: CursorPath,
    events_view: list[dict[str, Any]],
    incoming_command: str,
    project_root: Path,
    run_id: str,
    append_fn: Callable[[dict[str, Any]], Any],
    raise_on_exhausted: bool,
) -> tuple[Any, tuple[str, ...]] | None:
    """Walk the cursor through nested entries and repeat-host expansions until we
    land on a CodeStep / AttestedStep leaf. Mutates ``cursor.frames`` and pushes
    auto-traversal events through ``append_fn``. ``events_view`` must be the list
    that ``append_fn`` extends (or that mirrors the on-disk log) so the helpers
    that scan prior events (``_count_iteration_failed``, the ``for_each_expanded``
    lookup) see the latest state.

    With ``raise_on_exhausted=True`` (gate dispatch) the helper raises
    ``TaskRunGateError`` when the plan is exhausted; with ``False`` (peek) it
    returns ``None`` so the caller can report exhaustion to the operator.
    """
    while True:
        if cursor.at_root_done:
            if raise_on_exhausted:
                _reject(slug, "plan is exhausted", abort=True)
            return None
        if cursor.top_exhausted:
            top = cursor.frames[-1]
            if top.repeat_step_id is not None:
                # Defensive: _finalize_cursor should have popped these already.
                cursor.frames.pop()
                cursor.frames[-1].child_index += 1
                continue
            exit_path_str = STEP_PATH_SEP.join(top.path_prefix)
            append_fn(make_nested_exited_event(exit_path_str, 0))
            cursor.frames.pop()
            cursor.frames[-1].child_index += 1
            continue
        top = cursor.frames[-1]
        current_step = top.plan.steps[top.child_index]
        current_path = top.path_prefix + (current_step.id,)
        path_str = STEP_PATH_SEP.join(current_path)
        repeat = getattr(current_step, "repeat", None)
        in_repeat_frame = top.repeat_step_id is not None
        if repeat is not None and not in_repeat_frame:
            if isinstance(repeat, RepeatUntil):
                _enter_repeat_until(
                    slug=slug,
                    cursor=cursor,
                    host=current_step,
                    repeat=repeat,
                    path_str=path_str,
                    parent_prefix=top.path_prefix,
                    events=events_view,
                    append_fn=append_fn,
                )
                continue
            if isinstance(repeat, RepeatForEach):
                _enter_repeat_for_each(
                    slug=slug,
                    cursor=cursor,
                    host=current_step,
                    repeat=repeat,
                    path_str=path_str,
                    parent_prefix=top.path_prefix,
                    events=events_view,
                    append_fn=append_fn,
                    project_root=project_root,
                    run_id=run_id,
                    incoming_command=incoming_command,
                )
                continue
        if isinstance(current_step, NestedStep):
            child_hash = _compute_inline_plan_hash(current_step.plan)
            append_fn(make_nested_entered_event(path_str, child_hash))
            cursor.frames.append(
                _Frame(plan=current_step.plan, path_prefix=current_path, child_index=0)
            )
            continue
        return current_step, current_path


@dataclass(frozen=True)
class PeekResult:
    """Read-only view of the next dispatchable step under the current cursor.

    Returned by ``peek_current_step`` for ``cmd_next`` / ``cmd_status`` /
    ``cmd_ack`` to inspect what the gate would dispatch on next without
    actually mutating ``events.jsonl``. ``exhausted=True`` covers both
    ``at_root_done`` (plan complete) and ``pinned_failure``
    (repeat.until on_exhaust=fail).
    """

    step: Any
    path_tuple: tuple[str, ...]
    iteration: int | None
    item_id: str | None
    exhausted: bool


def peek_current_step(
    plan: TaskPlan,
    events: Sequence[dict[str, Any]],
    slug: str,
    *,
    project_root: Path,
    run_id: str,
) -> PeekResult:
    """Walk the cursor exactly the way the gate would, but with a list-capturing
    ``append_fn`` so ``events.jsonl`` is never mutated.

    Shares ``_auto_traverse_to_leaf`` with ``gate_command`` so peek and dispatch
    cannot drift on iteration / for_each / nested transitions (FLAG-P5-003).
    The captured events are kept in ``events_view`` so prior-event scans inside
    the auto-traverse helpers (``_count_iteration_failed``, the
    ``for_each_expanded`` lookup) see them; after every append we let the helper
    proceed and re-evaluate the cursor — which is equivalent to recomputing
    ``derive_cursor(plan, events + captured, slug=slug)`` because the helper
    performs the same frame mutations that ``derive_cursor`` would on replay.
    """
    cursor = derive_cursor(plan, events, slug=slug)
    if cursor.pinned_failure is not None or cursor.at_root_done:
        return PeekResult(step=None, path_tuple=(), iteration=None, item_id=None, exhausted=True)

    events_view = list(events)
    captured: list[dict[str, Any]] = []

    def _peek_append(ev: dict[str, Any]) -> None:
        captured.append(ev)
        events_view.append(ev)

    leaf = _auto_traverse_to_leaf(
        slug=slug,
        cursor=cursor,
        events_view=events_view,
        incoming_command="",
        project_root=project_root,
        run_id=run_id,
        append_fn=_peek_append,
        raise_on_exhausted=False,
    )
    if leaf is None:
        return PeekResult(step=None, path_tuple=(), iteration=None, item_id=None, exhausted=True)
    step, path_tuple = leaf
    top = cursor.frames[-1]
    iteration = top.iteration if top.repeat_step_id is not None else None
    item_id = top.item_id if top.repeat_step_id is not None else None
    return PeekResult(
        step=step,
        path_tuple=path_tuple,
        iteration=iteration,
        item_id=item_id,
        exhausted=False,
    )


def gate_command(
    slug: str,
    command: str,
    argv: Sequence[str],
    *,
    root: str | Path | None = None,
    reentry: bool = False,
) -> GateDecision:
    active_run = read_active_run(slug, root=root)
    if active_run is None:
        if not is_in_task_run(slug):
            return GateDecision(active=False)
        _reject(slug, "active_run.json is missing", abort=True)

    project_root = project_dir(slug, root=root)
    plan_path = project_root / "plan.json"
    plan_hash = compute_plan_hash(plan_path)
    if plan_hash != active_run["plan_hash"]:
        _reject(slug, "plan.json hash does not match active_run.json pin", abort=True)

    run_id = active_run["run_id"]
    events_path = project_root / "runs" / run_id / "events.jsonl"
    ok, _last_index, error = verify_chain(events_path)
    if not ok:
        _reject(slug, error or "events.jsonl chain integrity check failed", abort=True)

    plan = load_plan(plan_path)
    events = read_events(events_path)
    cursor = derive_cursor(plan, events, slug=slug)
    if cursor.pinned_failure is not None:
        reason, _host_path = cursor.pinned_failure
        raise TaskRunGateError(reason=reason, recovery=f"artagents abort --project {slug}")
    run_started_actor = _find_run_started_actor(events)

    # Auto-traverse: nested_entered/exited for nested plans; iteration_started/
    # for_each_expanded/item_started for repeat hosts. We loop until we land on a
    # dispatchable leaf (CodeStep or AttestedStep) inside the appropriate frame.
    events_view = list(events)

    def _gate_append(ev: dict[str, Any]) -> None:
        append_event(events_path, ev)
        events_view.append(ev)

    leaf = _auto_traverse_to_leaf(
        slug=slug,
        cursor=cursor,
        events_view=events_view,
        incoming_command=command,
        project_root=project_root,
        run_id=run_id,
        append_fn=_gate_append,
        raise_on_exhausted=True,
    )
    if leaf is None:
        # Defensive: raise_on_exhausted=True should always raise inside the helper.
        _reject(slug, "plan is exhausted", abort=True)
    current_step, current_path = leaf
    top = cursor.frames[-1]
    path_str = STEP_PATH_SEP.join(current_path)

    iteration = top.iteration if top.repeat_step_id is not None else None
    item_id = top.item_id if top.repeat_step_id is not None else None

    if isinstance(current_step, CodeStep):
        return _dispatch_code(
            slug=slug,
            command=command,
            step=current_step,
            path_str=path_str,
            path_tuple=current_path,
            events_path=events_path,
            run_id=run_id,
            reentry=reentry,
            project_root=project_root,
            iteration=iteration,
            item_id=item_id,
        )
    if isinstance(current_step, AttestedStep):
        return _dispatch_attested(
            slug=slug,
            command=command,
            step=current_step,
            path_str=path_str,
            path_tuple=current_path,
            events_path=events_path,
            run_id=run_id,
            run_started_actor=run_started_actor,
            project_root=project_root,
            iteration=iteration,
            item_id=item_id,
        )
    raise TaskRunGateError(
        reason=f"unexpected step kind: {type(current_step).__name__}",
        recovery=f"artagents next --project {slug}",
    )


def _count_iteration_failed(events: Sequence[dict[str, Any]], host_path: str) -> int:
    return sum(
        1
        for ev in events
        if isinstance(ev, dict)
        and ev.get("kind") == "iteration_failed"
        and _path_str_from_event(ev) == host_path
    )


EXHAUST_OVERRIDE_ID = "exhaust-override"


def _has_iteration_exhausted(events: Sequence[dict[str, Any]], host_path: str) -> dict[str, Any] | None:
    for ev in events:
        if (
            isinstance(ev, dict)
            and ev.get("kind") == "iteration_exhausted"
            and _path_str_from_event(ev) == host_path
        ):
            return ev
    return None


def _make_exhaust_override_step(slug: str, host_path: str) -> AttestedStep:
    override_path = f"{host_path}{STEP_PATH_SEP}{EXHAUST_OVERRIDE_ID}"
    return AttestedStep(
        id=EXHAUST_OVERRIDE_ID,
        command=f"ack --project {slug} --step {override_path}",
        instructions="repeat.until max_iterations exhausted; human override required to advance",
        ack=AckRule(kind="actor"),
    )


def _enter_repeat_until(
    *,
    slug: str,
    cursor: CursorPath,
    host: Any,
    repeat: RepeatUntil,
    path_str: str,
    parent_prefix: tuple[str, ...],
    events: Sequence[dict[str, Any]],
    append_fn: Callable[[dict[str, Any]], Any],
) -> None:
    failed = _count_iteration_failed(events, path_str)
    iteration = failed + 1
    path_tuple = parent_prefix + (host.id,)
    if iteration > repeat.max_iterations:
        existing = _has_iteration_exhausted(events, path_str)
        if existing is None:
            append_fn(
                make_iteration_exhausted_event(
                    path_tuple,
                    on_exhaust=repeat.on_exhaust,
                    max_iterations=repeat.max_iterations,
                )
            )
        if repeat.on_exhaust == "fail":
            raise TaskRunGateError(
                reason="repeat.until max_iterations exhausted",
                recovery=f"artagents abort --project {slug}",
            )
        # escalate: park on a synthetic exhaust-override attested step.
        override_step = _make_exhaust_override_step(slug, path_str)
        override_plan = TaskPlan(
            plan_id=f"__exhaust_{host.id}",
            version=1,
            steps=(override_step,),
        )
        cursor.frames.append(
            _Frame(
                plan=override_plan,
                path_prefix=path_tuple,
                child_index=0,
                repeat_step_id=host.id,
            )
        )
        return
    append_fn(make_iteration_started_event(path_tuple, iteration))
    cursor.frames.append(_make_iteration_frame(host, parent_prefix, iteration))


def _resolve_for_each_items(
    *,
    slug: str,
    repeat: RepeatForEach,
    project_root: Path,
    run_id: str,
) -> tuple[str, ...]:
    if repeat.items_source == "static":
        items = repeat.items
    else:
        target_id, produces_name = parse_from_ref(repeat.from_ref or "")
        prior_step_dir = step_dir_for_path(slug, run_id, (target_id,), root=project_root.parent)
        # Find the prior step's declared produces path. We need the plan for that.
        # We re-load plan.json which is allowed at gate_command (not in derive_cursor).
        plan = load_plan(project_root / "plan.json")
        target_step = next((s for s in plan.steps if s.id == target_id), None)
        if target_step is None:
            raise TaskRunGateError(
                reason=f"for_each.from references unknown sibling step {target_id!r}",
                recovery=f"artagents abort --project {slug}",
            )
        produces_entry = next((p for p in target_step.produces if p.name == produces_name), None)
        if produces_entry is None:
            raise TaskRunGateError(
                reason=f"for_each.from references unknown produces {produces_name!r}",
                recovery=f"artagents abort --project {slug}",
            )
        try:
            payload = json.loads((prior_step_dir / produces_entry.path).read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
            raise TaskRunGateError(
                reason=f"for_each.from cannot read produces JSON: {exc}",
                recovery=f"artagents abort --project {slug}",
            ) from exc
        if not isinstance(payload, list):
            raise TaskRunGateError(reason="for_each items must be unique strings", recovery=f"artagents next --project {slug}")
        items = tuple(payload)
    if not all(isinstance(x, str) and x for x in items):
        raise TaskRunGateError(reason="for_each items must be unique strings", recovery=f"artagents next --project {slug}")
    if len(set(items)) != len(items):
        raise TaskRunGateError(reason="for_each items must be unique strings", recovery=f"artagents next --project {slug}")
    return items


def _enter_repeat_for_each(
    *,
    slug: str,
    cursor: CursorPath,
    host: Any,
    repeat: RepeatForEach,
    path_str: str,
    parent_prefix: tuple[str, ...],
    events: Sequence[dict[str, Any]],
    append_fn: Callable[[dict[str, Any]], Any],
    project_root: Path,
    run_id: str,
    incoming_command: str,
) -> str | None:
    # FLAG-P3-004: scan events for an existing for_each_expanded; if absent, append once.
    existing = next(
        (
            ev
            for ev in events
            if isinstance(ev, dict)
            and ev.get("kind") == "for_each_expanded"
            and _path_str_from_event(ev) == path_str
        ),
        None,
    )
    if existing is None:
        items = _resolve_for_each_items(slug=slug, repeat=repeat, project_root=project_root, run_id=run_id)
        path_tuple = parent_prefix + (host.id,)
        append_fn(make_for_each_expanded_event(path_tuple, items))
        cursor.for_each_progress[path_str] = {"items": items, "completed": set()}
    else:
        items = tuple(existing.get("item_ids") or ())
    progress = cursor.for_each_progress.setdefault(path_str, {"items": items, "completed": set()})
    completed = progress["completed"]
    # For attested host: the incoming command may target a specific item via --item.
    target_item: str | None = None
    if isinstance(host, AttestedStep):
        _, args = match_attested_command(incoming_command, host.command)
        if args.item is not None:
            target_item = args.item
    if target_item is None:
        # Pick first not-yet-completed item.
        target_item = next((it for it in items if it not in completed), None)
    if target_item is None:
        # All items done — finalize will pop. Just return.
        return None
    if target_item not in items:
        _reject(slug, f"for_each --item {target_item!r} not in expanded item set", abort=False)
    if target_item in completed:
        _reject(slug, f"for_each --item {target_item!r} already completed", abort=False)
    path_tuple = parent_prefix + (host.id,)
    append_fn(make_item_started_event(path_tuple, target_item))
    cursor.frames.append(_make_item_frame(host, parent_prefix, target_item))
    return target_item


def _dispatch_code(
    *,
    slug: str,
    command: str,
    step: CodeStep,
    path_str: str,
    path_tuple: tuple[str, ...],
    events_path: Path,
    run_id: str,
    reentry: bool,
    project_root: Path,
    iteration: int | None = None,
    item_id: str | None = None,
) -> GateDecision:
    if command != step.command:
        _reject(slug, "incoming command does not match plan[cursor]", abort=False)

    if reentry:
        # FLAG-P3-005: scan back to the latest event for THIS plan_step_id rather than events[-1];
        # produces_check_failed must permit redispatch (cursor hasn't advanced).
        events = read_events(events_path)
        latest = _latest_event_for_step(events, path_str)
        if (
            isinstance(latest, dict)
            and latest.get("kind") == "step_dispatched"
            and latest.get("command") == command
        ):
            apply_task_run_env(run_id, slug, path_str, item_id=item_id, iteration=iteration)
            return _code_decision(
                run_id=run_id,
                slug=slug,
                path_str=path_str,
                path_tuple=path_tuple,
                events_path=events_path,
                produces=step.produces,
                project_root=project_root,
                reentry=True,
                iteration=iteration,
                item_id=item_id,
            )
        if isinstance(latest, dict) and latest.get("kind") == "produces_check_failed":
            append_event(events_path, make_step_dispatched_event(path_str, command))
            apply_task_run_env(run_id, slug, path_str, item_id=item_id, iteration=iteration)
            return _code_decision(
                run_id=run_id,
                slug=slug,
                path_str=path_str,
                path_tuple=path_tuple,
                events_path=events_path,
                produces=step.produces,
                project_root=project_root,
                reentry=False,
                iteration=iteration,
                item_id=item_id,
            )
        _reject(slug, "incoming command does not match plan[cursor]", abort=False)

    append_event(events_path, make_step_dispatched_event(path_str, command))
    apply_task_run_env(run_id, slug, path_str, item_id=item_id, iteration=iteration)
    return _code_decision(
        run_id=run_id,
        slug=slug,
        path_str=path_str,
        path_tuple=path_tuple,
        events_path=events_path,
        produces=step.produces,
        project_root=project_root,
        reentry=False,
        iteration=iteration,
        item_id=item_id,
    )


def _code_decision(
    *,
    run_id: str,
    slug: str,
    path_str: str,
    path_tuple: tuple[str, ...],
    events_path: Path,
    produces: tuple[ProducesEntry, ...],
    project_root: Path,
    reentry: bool,
    iteration: int | None = None,
    item_id: str | None = None,
) -> GateDecision:
    return GateDecision(
        active=True,
        run_id=run_id,
        plan_step_id=path_str,
        events_path=events_path,
        reentry=reentry,
        step_kind="code",
        slug=slug,
        plan_step_path=path_tuple,
        produces=produces,
        project_root=project_root,
        iteration=iteration,
        item_id=item_id,
    )


def _latest_event_for_step(events: Sequence[dict[str, Any]], path_str: str) -> dict[str, Any] | None:
    path_list = path_str.split(STEP_PATH_SEP)
    for ev in reversed(events):
        if not isinstance(ev, dict):
            continue
        if ev.get("plan_step_id") == path_str:
            return ev
        if ev.get("plan_step_path") == path_list:
            return ev
    return None


def _dispatch_attested(
    *,
    slug: str,
    command: str,
    step: AttestedStep,
    path_str: str,
    path_tuple: tuple[str, ...],
    events_path: Path,
    run_id: str,
    run_started_actor: str | None,
    project_root: Path,
    iteration: int | None = None,
    item_id: str | None = None,
) -> GateDecision:
    matched, args = match_attested_command(command, step.command)
    if not matched:
        _reject(slug, "incoming command does not match plan[cursor]", abort=False)

    attestor_kind, attestor_id = validate_attested_identity(
        slug=slug,
        step=step,
        args=args,
        run_started_actor=run_started_actor,
    )

    if item_id is not None:
        append_event(
            events_path,
            make_item_attested_event(
                path_tuple,
                item_id,
                attestor_kind=attestor_kind,
                attestor_id=attestor_id,
                evidence=args.evidence,
            ),
        )
    else:
        append_event(
            events_path,
            make_step_attested_event(path_str, attestor_kind, attestor_id, args.evidence),
        )
    decision = GateDecision(
        active=True,
        run_id=run_id,
        plan_step_id=path_str,
        events_path=events_path,
        reentry=False,
        step_kind="attested",
        slug=slug,
        plan_step_path=path_tuple,
        produces=step.produces,
        project_root=project_root,
        iteration=iteration,
        item_id=item_id,
    )
    if step.produces:
        _run_inline_checks(decision, step.produces)
    if iteration is not None:
        feedback = _extract_iterate_feedback(args.evidence)
        if feedback is not None:
            write_iteration_feedback(decision, feedback)
            append_event(
                events_path,
                make_iteration_failed_event(
                    path_tuple,
                    iteration,
                    reason="iterate_feedback",
                ),
            )
    return decision


def _extract_iterate_feedback(evidence: tuple[str, ...]) -> str | None:
    for item in evidence:
        if item.startswith(ITERATE_FEEDBACK_PREFIX):
            return item[len(ITERATE_FEEDBACK_PREFIX):]
    return None


def write_iteration_feedback(decision: GateDecision, feedback: str) -> None:
    if (
        decision.slug is None
        or decision.run_id is None
        or decision.iteration is None
        or decision.project_root is None
        or not decision.plan_step_path
    ):
        return
    iter_dir = step_dir_for_path(
        decision.slug,
        decision.run_id,
        decision.plan_step_path,
        iteration=decision.iteration,
        root=decision.project_root.parent,
    )
    iter_dir.mkdir(parents=True, exist_ok=True)
    feedback_path = iter_dir / "feedback.json"
    cumulative: list[str] = []
    if decision.iteration > 1:
        prev_dir = step_dir_for_path(
            decision.slug,
            decision.run_id,
            decision.plan_step_path,
            iteration=decision.iteration - 1,
            root=decision.project_root.parent,
        )
        prev_path = prev_dir / "feedback.json"
        if prev_path.exists():
            try:
                prev = json.loads(prev_path.read_text(encoding="utf-8"))
                if isinstance(prev, list):
                    cumulative = [str(x) for x in prev]
            except (json.JSONDecodeError, OSError):
                cumulative = []
    cumulative.append(feedback)
    feedback_path.write_text(
        json.dumps(cumulative, ensure_ascii=False),
        encoding="utf-8",
    )


def match_attested_command(incoming: str, expected_prefix: str) -> tuple[bool, AttestedArgs]:
    """Strip ``--agent``/``--actor``/``--evidence``/``--item`` (repeatable evidence)
    tokens from ``incoming`` and compare the canonical remainder to ``expected_prefix``.
    """
    try:
        tokens = shlex.split(incoming)
    except ValueError:
        return False, AttestedArgs(agent=None, actor=None, evidence=())
    agent: str | None = None
    actor: str | None = None
    item: str | None = None
    evidence: list[str] = []
    remaining: list[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == "--agent" and i + 1 < len(tokens):
            agent = tokens[i + 1]
            i += 2
            continue
        if token == "--actor" and i + 1 < len(tokens):
            actor = tokens[i + 1]
            i += 2
            continue
        if token == "--item" and i + 1 < len(tokens):
            item = tokens[i + 1]
            i += 2
            continue
        if token == "--evidence" and i + 1 < len(tokens):
            evidence.append(tokens[i + 1])
            i += 2
            continue
        remaining.append(token)
        i += 1
    rejoined = " ".join(shlex.quote(token) for token in remaining)
    matched = rejoined == expected_prefix
    return matched, AttestedArgs(agent=agent, actor=actor, evidence=tuple(evidence), item=item)


def validate_attested_identity(
    *,
    slug: str,
    step: AttestedStep,
    args: AttestedArgs,
    run_started_actor: str | None,
) -> tuple[str, str]:
    if args.agent is None and args.actor is None:
        _reject(slug, "attested step requires --agent or --actor", abort=False)
    if args.agent is not None and args.actor is not None:
        _reject(slug, "attested step rejects both --agent and --actor", abort=False)
    if step.ack.kind == "agent":
        if args.agent is None:
            _reject(slug, "attested step ack.kind=agent requires --agent", abort=False)
        return "agent", args.agent  # type: ignore[return-value]
    # ack.kind == "actor"
    if args.actor is None:
        _reject(slug, "attested step ack.kind=actor requires --actor", abort=False)
    if task_actor_env() != args.actor:
        _reject(slug, "attested --actor does not match ARTAGENTS_ACTOR env", abort=False)
    # FLAG-005: self-ack rejection only applies to actor attestations because agents
    # do not start runs in V1; an agent_id on run_started would be required to
    # symmetrically block agent self-acks, which is out of scope for Phase 2.
    if (
        run_started_actor is not None
        and run_started_actor == args.actor
        and task_actor_env() == args.actor
    ):
        _reject(slug, "self-ack rejected", abort=False)
    return "actor", args.actor  # type: ignore[return-value]


def record_dispatch_complete(decision: GateDecision, returncode: int) -> None:
    if not decision.active or decision.events_path is None or decision.plan_step_id is None:
        return
    if decision.step_kind == "attested":
        # attested steps are advanced by step_attested itself; do not double-emit
        return
    append_event(
        decision.events_path,
        make_step_completed_event(decision.plan_step_id, returncode),
    )
    if decision.produces:
        _run_inline_checks(decision, decision.produces)


# step_dir_for_path is the ONLY directory API used in this gate path (FLAG-P3-001).
def _run_inline_checks(decision: GateDecision, produces: tuple[ProducesEntry, ...]) -> bool:
    if (
        decision.events_path is None
        or decision.run_id is None
        or decision.slug is None
        or decision.project_root is None
        or not decision.plan_step_path
    ):
        return True
    projects_root = decision.project_root.parent
    step_dir = step_dir_for_path(
        decision.slug,
        decision.run_id,
        decision.plan_step_path,
        iteration=decision.iteration,
        item_id=decision.item_id,
        root=projects_root,
    )
    for entry in produces:
        artifact_path = step_dir / entry.path
        result = entry.check.run(artifact_path)
        if not result.ok:
            append_event(
                decision.events_path,
                make_produces_check_failed_event(
                    decision.plan_step_path,
                    entry.name,
                    check_id=entry.check.check_id,
                    reason=result.reason,
                ),
            )
            if decision.iteration is not None:
                append_event(
                    decision.events_path,
                    make_iteration_failed_event(
                        decision.plan_step_path,
                        decision.iteration,
                        reason=f"produces check failed: {entry.name}",
                    ),
                )
            else:
                append_event(
                    decision.events_path,
                    make_cursor_rewind_event(
                        decision.plan_step_path,
                        reason=f"produces check failed: {entry.name}",
                    ),
                )
            return False
        cas_sha256 = _intern_produces_artifact(decision, artifact_path)
        append_event(
            decision.events_path,
            make_produces_check_passed_event(
                decision.plan_step_path,
                entry.name,
                check_id=entry.check.check_id,
                cas_sha256=cas_sha256,
            ),
        )
    return True


def _intern_produces_artifact(decision: GateDecision, artifact_path: Path) -> str | None:
    if decision.project_root is None:
        return None
    if artifact_path.is_symlink():
        return None
    cas_target = intern(decision.project_root, artifact_path)
    link_into_produces(cas_target, artifact_path)
    return cas_target.name


def record_step_attested(
    decision: GateDecision,
    attestor_kind: str,
    attestor_id: str,
    evidence: tuple[str, ...] = (),
) -> None:
    """Reserved for Phase 5 lifecycle verbs; gate emits inline in Phase 2."""
    if not decision.active or decision.events_path is None or decision.plan_step_id is None:
        return
    append_event(
        decision.events_path,
        make_step_attested_event(decision.plan_step_id, attestor_kind, attestor_id, evidence),
    )


def record_nested_entered(decision: GateDecision, child_plan_hash: str) -> None:
    """Reserved for Phase 5 lifecycle verbs; gate emits inline in Phase 2."""
    if not decision.active or decision.events_path is None or decision.plan_step_id is None:
        return
    append_event(
        decision.events_path,
        make_nested_entered_event(decision.plan_step_id, child_plan_hash),
    )


def record_nested_exited(decision: GateDecision, returncode: int) -> None:
    """Reserved for Phase 5 lifecycle verbs; gate emits inline in Phase 2."""
    if not decision.active or decision.events_path is None or decision.plan_step_id is None:
        return
    append_event(
        decision.events_path,
        make_nested_exited_event(decision.plan_step_id, returncode),
    )


def command_for_argv(argv: Sequence[str]) -> str:
    tokens = [str(token) for token in argv]
    if len(tokens) >= 3 and Path(tokens[0]).name.startswith("python") and tokens[1:3] == ["-m", "artagents"]:
        tokens = tokens[3:]
    elif tokens and Path(tokens[0]).name.endswith("artagents"):
        tokens = tokens[1:]
    return " ".join(shlex.quote(token) for token in tokens)


def _compute_inline_plan_hash(plan: TaskPlan) -> str:
    digest = hashlib.sha256(canonical_event_json(plan.to_dict()).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _find_run_started_actor(events: Sequence[dict[str, Any]]) -> str | None:
    for event in events:
        if event.get("kind") == "run_started":
            actor = event.get("actor")
            return actor if isinstance(actor, str) else None
    return None


def _reject(slug: str, reason: str, *, abort: bool) -> None:
    verb = "abort" if abort else "next"
    raise TaskRunGateError(reason=reason, recovery=f"artagents {verb} --project {slug}")
