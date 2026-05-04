"""Task-run dispatch gate.

Phase 2 attested/nested handling is kernel-only; Phase 5 will add the
``artagents ack`` / ``artagents next`` lifecycle verbs that drive the
``record_step_attested`` / ``record_nested_entered`` / ``record_nested_exited``
helpers exposed for symmetry below. The gate itself emits ``step_attested``,
``nested_entered``, and ``nested_exited`` events inline; the public helpers
have zero callers in Phase 2 (FLAG-007).
"""

from __future__ import annotations

import hashlib
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

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
    make_nested_entered_event,
    make_nested_exited_event,
    make_step_attested_event,
    make_step_completed_event,
    make_step_dispatched_event,
    read_events,
    verify_chain,
)
from artagents.core.task.plan import (
    STEP_PATH_SEP,
    AttestedStep,
    CodeStep,
    NestedStep,
    TaskPlan,
    compute_plan_hash,
    load_plan,
)


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


@dataclass(frozen=True)
class AttestedArgs:
    agent: str | None
    actor: str | None
    evidence: tuple[str, ...]


@dataclass
class _Frame:
    plan: TaskPlan
    path_prefix: tuple[str, ...]
    child_index: int = 0


@dataclass
class CursorPath:
    frames: list[_Frame] = field(default_factory=list)

    @property
    def at_root_done(self) -> bool:
        return len(self.frames) == 1 and self.frames[-1].child_index >= len(self.frames[-1].plan.steps)

    @property
    def top_exhausted(self) -> bool:
        top = self.frames[-1]
        return top.child_index >= len(top.plan.steps)


def derive_cursor(plan: TaskPlan, events: Sequence[dict[str, Any]]) -> CursorPath:
    """Replay ``events.jsonl`` left-to-right to reconstruct the path-stack cursor.

    Reconstructible from events alone (supports partial-replay resume):
    ``nested_entered`` pushes, ``nested_exited`` pops + advances parent,
    ``step_completed`` / ``step_attested`` advance the top frame,
    ``step_dispatched`` and ``run_started`` do not advance.
    """
    frames: list[_Frame] = [_Frame(plan=plan, path_prefix=(), child_index=0)]
    for event in events:
        kind = event.get("kind")
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
        elif kind == "nested_exited":
            if len(frames) <= 1:
                raise TaskRunGateError(
                    reason="nested_exited at root frame",
                    recovery="inspect events.jsonl",
                )
            frames.pop()
            frames[-1].child_index += 1
        elif kind in ("step_completed", "step_attested"):
            frames[-1].child_index += 1
        # step_dispatched / run_started: no-op
    return CursorPath(frames=frames)


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
    cursor = derive_cursor(plan, events)
    run_started_actor = _find_run_started_actor(events)

    # Auto-traverse nested steps: emit nested_entered/exited until we land on a leaf
    # (CodeStep or AttestedStep) or determine the plan is exhausted.
    while True:
        if cursor.at_root_done:
            _reject(slug, "plan is exhausted", abort=True)
        if cursor.top_exhausted:
            top = cursor.frames[-1]
            exit_path_str = STEP_PATH_SEP.join(top.path_prefix)
            append_event(events_path, make_nested_exited_event(exit_path_str, 0))
            cursor.frames.pop()
            cursor.frames[-1].child_index += 1
            continue
        top = cursor.frames[-1]
        current_step = top.plan.steps[top.child_index]
        current_path = top.path_prefix + (current_step.id,)
        path_str = STEP_PATH_SEP.join(current_path)
        if isinstance(current_step, NestedStep):
            child_hash = _compute_inline_plan_hash(current_step.plan)
            append_event(events_path, make_nested_entered_event(path_str, child_hash))
            cursor.frames.append(
                _Frame(plan=current_step.plan, path_prefix=current_path, child_index=0)
            )
            continue
        break

    if isinstance(current_step, CodeStep):
        return _dispatch_code(
            slug=slug,
            command=command,
            step=current_step,
            path_str=path_str,
            events_path=events_path,
            run_id=run_id,
            reentry=reentry,
        )
    if isinstance(current_step, AttestedStep):
        return _dispatch_attested(
            slug=slug,
            command=command,
            step=current_step,
            path_str=path_str,
            events_path=events_path,
            run_id=run_id,
            run_started_actor=run_started_actor,
        )
    raise TaskRunGateError(
        reason=f"unexpected step kind: {type(current_step).__name__}",
        recovery=f"artagents next --project {slug}",
    )


def _dispatch_code(
    *,
    slug: str,
    command: str,
    step: CodeStep,
    path_str: str,
    events_path: Path,
    run_id: str,
    reentry: bool,
) -> GateDecision:
    if command != step.command:
        _reject(slug, "incoming command does not match plan[cursor]", abort=False)

    if reentry:
        events = read_events(events_path)
        latest = events[-1] if events else None
        if (
            not isinstance(latest, dict)
            or latest.get("kind") != "step_dispatched"
            or latest.get("plan_step_id") != path_str
            or latest.get("command") != command
        ):
            _reject(slug, "incoming command does not match plan[cursor]", abort=False)
        apply_task_run_env(run_id, slug, path_str)
        return GateDecision(
            active=True,
            run_id=run_id,
            plan_step_id=path_str,
            events_path=events_path,
            reentry=True,
            step_kind="code",
        )

    append_event(events_path, make_step_dispatched_event(path_str, command))
    apply_task_run_env(run_id, slug, path_str)
    return GateDecision(
        active=True,
        run_id=run_id,
        plan_step_id=path_str,
        events_path=events_path,
        reentry=False,
        step_kind="code",
    )


def _dispatch_attested(
    *,
    slug: str,
    command: str,
    step: AttestedStep,
    path_str: str,
    events_path: Path,
    run_id: str,
    run_started_actor: str | None,
) -> GateDecision:
    matched, args = match_attested_command(command, step.command)
    if not matched:
        _reject(slug, "incoming command does not match plan[cursor]", abort=False)

    attestor_kind, attestor_id = _validate_attested_identity(
        slug=slug,
        step=step,
        args=args,
        run_started_actor=run_started_actor,
    )

    append_event(
        events_path,
        make_step_attested_event(path_str, attestor_kind, attestor_id, args.evidence),
    )
    return GateDecision(
        active=True,
        run_id=run_id,
        plan_step_id=path_str,
        events_path=events_path,
        reentry=False,
        step_kind="attested",
    )


def match_attested_command(incoming: str, expected_prefix: str) -> tuple[bool, AttestedArgs]:
    """Strip ``--agent``/``--actor``/``--evidence`` (repeatable) tokens from
    ``incoming`` and compare the canonical remainder to ``expected_prefix``.
    """
    try:
        tokens = shlex.split(incoming)
    except ValueError:
        return False, AttestedArgs(agent=None, actor=None, evidence=())
    agent: str | None = None
    actor: str | None = None
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
        if token == "--evidence" and i + 1 < len(tokens):
            evidence.append(tokens[i + 1])
            i += 2
            continue
        remaining.append(token)
        i += 1
    rejoined = " ".join(shlex.quote(token) for token in remaining)
    matched = rejoined == expected_prefix
    return matched, AttestedArgs(agent=agent, actor=actor, evidence=tuple(evidence))


def _validate_attested_identity(
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
