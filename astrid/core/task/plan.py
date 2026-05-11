"""Task plan helpers — collapsed Step schema (DRAFT, locked after hype spike T6)."""

from __future__ import annotations

import hashlib
import json
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Literal, Union

from astrid.core.project.paths import project_dir, validate_project_slug, validate_run_id
from astrid.core.task.events import canonical_event_json
from astrid.verify import Check, canonical_check_params, file_nonempty


STEP_PATH_SEP = "/"

AdapterKind = Literal["local", "manual", "remote-artifact"]
ADAPTERS: tuple[AdapterKind, ...] = ("local", "manual", "remote-artifact")
AssigneeForm = Literal["system", "any-agent", "any-human", "agent", "actor"]
SupersedeScope = Literal["all", "future-iterations", "future-items"]
SUPERSEDE_SCOPES: tuple[SupersedeScope, ...] = ("all", "future-iterations", "future-items")


class TaskPlanError(ValueError):
    """Raised when plan.json is malformed."""


@dataclass(frozen=True)
class AckRule:
    kind: Literal["agent", "actor"]


@dataclass(frozen=True)
class ProducesEntry:
    name: str
    path: str
    check: Check


@dataclass(frozen=True)
class RepeatUntil:
    condition: Literal["user_approves", "verifier_passes", "quorum"]
    max_iterations: int
    on_exhaust: Literal["escalate", "fail"]
    quorum_n: int | None = None
    kind: Literal["until"] = "until"


@dataclass(frozen=True)
class RepeatForEach:
    items_source: Literal["static", "from"]
    items: tuple[str, ...] = ()
    from_ref: str | None = None
    kind: Literal["for_each"] = "for_each"


Repeat = Union[RepeatUntil, RepeatForEach]


@dataclass(frozen=True)
class CostEntry:
    amount: float
    currency: str
    source: str


@dataclass(frozen=True)
class SupersededRef:
    to_version: int
    scope: SupersedeScope


@dataclass(frozen=True)
class Step:
    """Single collapsed step shape — replaces CodeStep/AttestedStep/NestedStep."""

    id: str
    adapter: AdapterKind = "local"
    version: int = 1
    requires_ack: bool = False
    assignee: str = "system"
    produces: tuple[ProducesEntry, ...] = ()
    repeat: Repeat | None = None
    command: str | None = None
    instructions: str | None = None
    children: tuple["Step", ...] | None = None
    cost: CostEntry | None = None
    superseded_by: SupersededRef | None = None
    # Optional ack rule preserved for migrated attested steps (carries kind=agent|actor).
    ack: AckRule | None = None

    @property
    def plan(self) -> "TaskPlan | None":
        """Compat shim for legacy NestedStep.plan access. Returns None on leaves."""
        if self.children is None:
            return None
        return TaskPlan(plan_id=f"_inline_{self.id}", version=2, steps=self.children)

    def __post_init__(self) -> None:
        # Structural invariants only — adapter/command-shape lives in _validate_step.
        if self.command is None and self.children is None:
            raise TaskPlanError(
                f"step {self.id!r}: must have either 'command' (leaf) or 'children' (group)"
            )
        if self.command is not None and self.children is not None:
            raise TaskPlanError(
                f"step {self.id!r}: cannot have both 'command' and 'children'"
            )
        _parse_assignee(self.assignee, step_id=self.id)
        # Phase 1–3 v2-rejection invariant: until T8 retires this, only v1 is constructible.
        if self.version != 1:
            raise TaskPlanError(
                f"step {self.id!r}: version must be 1 in Phase 1–3 (got {self.version}); supersede support unlocks at T8"
            )


def is_group_step(step: "Step") -> bool:
    """True for group steps (children present)."""
    return step.children is not None


def is_leaf_step(step: "Step") -> bool:
    """True for leaf steps (command present, no children)."""
    return step.children is None


def is_code_kind(step: "Step") -> bool:
    """Legacy CodeStep semantics: leaf, no ack required."""
    return is_leaf_step(step) and not step.requires_ack


def is_attested_kind(step: "Step") -> bool:
    """Legacy AttestedStep semantics: leaf, requires_ack."""
    return is_leaf_step(step) and step.requires_ack


# Legacy aliases kept ONLY so cross-module imports survive the T2→T3 window.
# These classes are never constructed by the validator anymore. T3 will rewrite
# isinstance dispatches and these placeholders are removed in T3/T24.
class _LegacyStepPlaceholder:
    """Placeholder so legacy `from .plan import CodeStep` imports do not crash mid-sweep."""


class CodeStep(_LegacyStepPlaceholder):
    pass


class AttestedStep(_LegacyStepPlaceholder):
    pass


class NestedStep(_LegacyStepPlaceholder):
    pass


TaskPlanStep = Step  # legacy alias


@dataclass(frozen=True)
class TaskPlan:
    plan_id: str
    version: int
    steps: tuple[Step, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "version": self.version,
            "steps": [_step_to_dict(step) for step in self.steps],
        }


def load_plan(plan_path: str | Path) -> TaskPlan:
    payload = _read_plan_payload(plan_path)
    return _validate_plan(payload)


def compute_plan_hash(plan_path: str | Path) -> str:
    payload = _read_plan_payload(plan_path)
    _validate_plan(payload)
    digest = hashlib.sha256(canonical_event_json(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def step_dir_for_path(
    slug: str,
    run_id: str,
    plan_step_path: tuple[str, ...],
    *,
    step_version: int = 1,
    iteration: int | None = None,
    item_id: str | None = None,
    root: str | Path | None = None,
) -> Path:
    validate_project_slug(slug)
    validate_run_id(run_id)
    if not plan_step_path:
        raise TaskPlanError("plan_step_path must contain at least one segment")
    for segment in plan_step_path:
        validate_run_id(segment)
    if not isinstance(step_version, int) or isinstance(step_version, bool) or step_version < 1:
        raise TaskPlanError("step_dir_for_path: step_version must be an int >= 1")
    if iteration is not None and item_id is not None:
        raise TaskPlanError("step_dir_for_path: iteration and item_id are mutually exclusive")
    base = project_dir(slug, root=root) / "runs" / run_id / "steps"
    for idx, segment in enumerate(plan_step_path):
        base = base / segment
        # Versioned segment lives directly under the leaf step id only.
        if idx == len(plan_step_path) - 1:
            base = base / f"v{step_version}"
    if iteration is not None:
        if not isinstance(iteration, int) or isinstance(iteration, bool) or iteration < 1:
            raise TaskPlanError("step_dir_for_path: iteration must be an int >= 1")
        base = base / "iterations" / f"{iteration:03d}"
    elif item_id is not None:
        validate_run_id(item_id)
        base = base / "items" / item_id
    return base


def step_dir_for(
    slug: str,
    run_id: str,
    plan_step_id: str,
    *,
    step_version: int = 1,
    root: str | Path | None = None,
) -> Path:
    return step_dir_for_path(slug, run_id, (plan_step_id,), step_version=step_version, root=root)


def iter_steps_with_path(plan: TaskPlan) -> Iterator[tuple[tuple[str, ...], Step]]:
    """Yield ``(path, step)`` in pre-order for every step in the plan tree."""

    def _walk(steps: tuple[Step, ...], prefix: tuple[str, ...]) -> Iterator[tuple[tuple[str, ...], Step]]:
        for step in steps:
            path = prefix + (step.id,)
            yield path, step
            if step.children is not None:
                yield from _walk(step.children, path)

    yield from _walk(plan.steps, ())


def parse_from_ref(from_ref: str) -> tuple[str, str]:
    sep = ".produces."
    idx = from_ref.find(sep)
    if idx <= 0 or idx + len(sep) >= len(from_ref):
        raise TaskPlanError(
            f"repeat.for_each.from must match '<step-id>.produces.<name>', got {from_ref!r}"
        )
    return from_ref[:idx], from_ref[idx + len(sep):]


def _parse_assignee(assignee: str, *, step_id: str) -> tuple[AssigneeForm, str | None]:
    """Validate assignee string and return (form, identity-or-None)."""
    if not isinstance(assignee, str) or not assignee:
        raise TaskPlanError(f"step {step_id!r}: assignee must be a non-empty string")
    if assignee in ("system", "any-agent", "any-human"):
        return assignee, None  # type: ignore[return-value]
    for prefix, kind in (("agent:", "agent"), ("human:", "actor")):
        if assignee.startswith(prefix):
            ident = assignee[len(prefix):]
            if not ident:
                raise TaskPlanError(
                    f"step {step_id!r}: assignee {assignee!r} missing identity after {prefix!r}"
                )
            return kind, ident  # type: ignore[return-value]
    raise TaskPlanError(
        f"step {step_id!r}: assignee must be one of 'system'|'any-agent'|'any-human'|'agent:<id>'|'human:<name>', got {assignee!r}"
    )


def _step_to_dict(step: Step) -> dict[str, Any]:
    out: dict[str, Any] = {"id": step.id, "adapter": step.adapter}
    if step.version != 1:
        out["version"] = step.version
    if step.requires_ack:
        out["requires_ack"] = True
    if step.assignee != "system":
        out["assignee"] = step.assignee
    if step.command is not None:
        out["command"] = step.command
    if step.instructions is not None:
        out["instructions"] = step.instructions
    if step.children is not None:
        out["children"] = [_step_to_dict(c) for c in step.children]
    if step.produces:
        out["produces"] = _produces_to_dict(step.produces)
    if step.repeat is not None:
        out["repeat"] = _repeat_to_dict(step.repeat)
    if step.ack is not None:
        out["ack"] = {"kind": step.ack.kind}
    if step.cost is not None:
        out["cost"] = {"amount": step.cost.amount, "currency": step.cost.currency, "source": step.cost.source}
    if step.superseded_by is not None:
        out["superseded_by"] = {"to_version": step.superseded_by.to_version, "scope": step.superseded_by.scope}
    return out


def _produces_to_dict(produces: tuple[ProducesEntry, ...]) -> dict[str, Any]:
    sorted_entries = sorted(produces, key=lambda entry: entry.name)
    return {
        entry.name: {
            "path": entry.path,
            "check": {
                "check_id": entry.check.check_id,
                "params": canonical_check_params(entry.check.params),
                "sentinel": entry.check.sentinel,
            },
        }
        for entry in sorted_entries
    }


def _repeat_to_dict(repeat: Repeat) -> dict[str, Any]:
    if isinstance(repeat, RepeatUntil):
        out: dict[str, Any] = {
            "until": repeat.condition,
            "max_iterations": repeat.max_iterations,
            "on_exhaust": repeat.on_exhaust,
        }
        if repeat.quorum_n is not None:
            out["quorum_n"] = repeat.quorum_n
        return out
    if isinstance(repeat, RepeatForEach):
        if repeat.items_source == "static":
            return {"for_each": {"items": list(repeat.items)}}
        return {"for_each": {"from": repeat.from_ref}}
    raise TaskPlanError(f"unknown repeat type: {type(repeat)!r}")


def _read_plan_payload(plan_path: str | Path) -> Any:
    path = Path(plan_path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as exc:
        raise TaskPlanError(f"invalid JSON in {path}: {exc.msg}") from exc
    except OSError as exc:
        raise TaskPlanError(f"failed to read {path}: {exc}") from exc


def _read_legacy_plan_payload(plan_path: str | Path) -> Any:
    """Private accessor used by migrate_plans.py to load v1 plans bypassing validation."""
    return _read_plan_payload(plan_path)


def _validate_plan(payload: Any, *, _is_root: bool = True) -> TaskPlan:
    if not isinstance(payload, dict):
        raise TaskPlanError("plan must be an object")
    plan_id = payload.get("plan_id")
    version = payload.get("version")
    steps = payload.get("steps")
    if not isinstance(plan_id, str) or not plan_id:
        raise TaskPlanError("plan plan_id must be a non-empty string")
    if version != 2 or isinstance(version, bool):
        raise TaskPlanError("plan version must be 2")
    if not isinstance(steps, list):
        raise TaskPlanError("plan steps must be a list")

    validated_steps: list[Step] = []
    for index, step in enumerate(steps):
        validated_steps.append(_validate_step(step, index, validated_steps))

    plan = TaskPlan(plan_id=plan_id, version=2, steps=tuple(validated_steps))
    if _is_root:
        _assert_unique_paths(plan)
    return plan


def _validate_step(step: Any, index: int, prior_siblings: list[Step]) -> Step:
    if not isinstance(step, dict):
        raise TaskPlanError(f"plan steps[{index}] must be an object")
    step_id_raw = step.get("id")
    if not isinstance(step_id_raw, str) or not step_id_raw:
        raise TaskPlanError(f"plan steps[{index}].id must be a non-empty string")
    step_id = validate_run_id(step_id_raw)

    adapter = step.get("adapter", "local")
    if adapter not in ADAPTERS:
        raise TaskPlanError(
            f"plan steps[{index}].adapter must be one of {ADAPTERS}, got {adapter!r}"
        )

    requires_ack = step.get("requires_ack", False)
    if not isinstance(requires_ack, bool):
        raise TaskPlanError(f"plan steps[{index}].requires_ack must be a bool")

    assignee = step.get("assignee", "system")
    _parse_assignee(assignee, step_id=step_id)  # validates shape

    command = step.get("command")
    instructions = step.get("instructions")
    raw_children = step.get("children")

    if command is not None and not (isinstance(command, str) and command):
        raise TaskPlanError(f"plan steps[{index}].command must be a non-empty string when present")
    if instructions is not None and not (isinstance(instructions, str) and instructions):
        raise TaskPlanError(f"plan steps[{index}].instructions must be a non-empty string when present")

    children: tuple[Step, ...] | None = None
    if raw_children is not None:
        if not isinstance(raw_children, list):
            raise TaskPlanError(f"plan steps[{index}].children must be a list")
        if command is not None:
            raise TaskPlanError(f"plan steps[{index}]: leaf (command) and group (children) are mutually exclusive")
        validated_children: list[Step] = []
        for child_idx, child in enumerate(raw_children):
            validated_children.append(_validate_step(child, child_idx, validated_children))
        children = tuple(validated_children)
    elif command is None:
        raise TaskPlanError(f"plan steps[{index}]: must define either 'command' or 'children'")

    produces = _validate_produces(step.get("produces"), index, allow_legacy_list=(adapter == "local" and children is None))
    repeat = _validate_repeat(step.get("repeat"), index, prior_siblings)

    ack_raw = step.get("ack")
    ack: AckRule | None = None
    if ack_raw is not None:
        if not isinstance(ack_raw, dict):
            raise TaskPlanError(f"plan steps[{index}].ack must be an object")
        ack_kind = ack_raw.get("kind")
        if ack_kind not in {"agent", "actor"}:
            raise TaskPlanError(
                f"plan steps[{index}].ack.kind must be 'agent' or 'actor', got {ack_kind!r}"
            )
        ack = AckRule(kind=ack_kind)

    cost_raw = step.get("cost")
    cost: CostEntry | None = None
    if cost_raw is not None:
        if not isinstance(cost_raw, dict):
            raise TaskPlanError(f"plan steps[{index}].cost must be an object")
        amount = cost_raw.get("amount")
        currency = cost_raw.get("currency")
        source = cost_raw.get("source")
        if not isinstance(amount, (int, float)) or isinstance(amount, bool):
            raise TaskPlanError(f"plan steps[{index}].cost.amount must be a number")
        if not isinstance(currency, str) or not currency:
            raise TaskPlanError(f"plan steps[{index}].cost.currency must be a non-empty string")
        if not isinstance(source, str) or not source:
            raise TaskPlanError(f"plan steps[{index}].cost.source must be a non-empty string")
        cost = CostEntry(amount=float(amount), currency=currency, source=source)

    superseded_by_raw = step.get("superseded_by")
    superseded_by: SupersededRef | None = None
    if superseded_by_raw is not None:
        if not isinstance(superseded_by_raw, dict):
            raise TaskPlanError(f"plan steps[{index}].superseded_by must be an object")
        to_version = superseded_by_raw.get("to_version")
        scope = superseded_by_raw.get("scope")
        if not isinstance(to_version, int) or isinstance(to_version, bool) or to_version < 2:
            raise TaskPlanError(f"plan steps[{index}].superseded_by.to_version must be an int >= 2")
        if scope not in SUPERSEDE_SCOPES:
            raise TaskPlanError(
                f"plan steps[{index}].superseded_by.scope must be one of {SUPERSEDE_SCOPES}, got {scope!r}"
            )
        superseded_by = SupersededRef(to_version=to_version, scope=scope)

    version_field = step.get("version", 1)
    if not isinstance(version_field, int) or isinstance(version_field, bool) or version_field < 1:
        raise TaskPlanError(f"plan steps[{index}].version must be an int >= 1")

    new_step = Step(
        id=step_id,
        adapter=adapter,
        version=version_field,
        requires_ack=requires_ack,
        assignee=assignee,
        produces=produces,
        repeat=repeat,
        command=command,
        instructions=instructions,
        children=children,
        cost=cost,
        superseded_by=superseded_by,
        ack=ack,
    )

    # Post-construction adapter/command-shape checks. _reject_orchestrators_run
    # only runs on local-adapter leaves (per SC2: keys on step.adapter == 'local').
    if new_step.adapter == "local" and new_step.command is not None:
        _reject_orchestrators_run(new_step)
    if new_step.adapter == "manual":
        if new_step.command is None or not new_step.command.strip():
            raise TaskPlanError(
                f"plan steps[{index}]: manual adapter requires a non-empty command (dispatch payload)"
            )

    return new_step


def _validate_produces(raw: Any, index: int, *, allow_legacy_list: bool) -> tuple[ProducesEntry, ...]:
    if raw is None:
        return ()
    if isinstance(raw, list):
        if not allow_legacy_list:
            raise TaskPlanError(
                f"plan steps[{index}].produces must be a dict; legacy list form not allowed for this step kind"
            )
        if not raw:
            return ()
        entries: list[ProducesEntry] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, str) or not item:
                raise TaskPlanError(
                    f"plan steps[{index}].produces legacy list must contain non-empty strings"
                )
            name = Path(item).stem or item
            if name in seen:
                raise TaskPlanError(
                    f"plan steps[{index}].produces legacy list yields duplicate name {name!r}; use dict form"
                )
            seen.add(name)
            entries.append(ProducesEntry(name=name, path=item, check=file_nonempty()))
        return tuple(entries)
    if isinstance(raw, dict):
        entries = []
        for name in raw:
            if not isinstance(name, str) or not name:
                raise TaskPlanError(
                    f"plan steps[{index}].produces keys must be non-empty strings"
                )
            value = raw[name]
            if not isinstance(value, dict):
                raise TaskPlanError(
                    f"plan steps[{index}].produces[{name!r}] must be an object"
                )
            path_value = value.get("path")
            if not isinstance(path_value, str) or not path_value:
                raise TaskPlanError(
                    f"plan steps[{index}].produces[{name!r}].path must be a non-empty string"
                )
            check = _validate_check(value.get("check"), index, name)
            entries.append(ProducesEntry(name=name, path=path_value, check=check))
        return tuple(entries)
    raise TaskPlanError(
        f"plan steps[{index}].produces must be a dict (or legacy list for local-adapter leaf steps)"
    )


def _validate_check(raw: Any, index: int, produces_name: str) -> Check:
    if not isinstance(raw, dict):
        raise TaskPlanError(
            f"plan steps[{index}].produces[{produces_name!r}].check must be an object"
        )
    check_id = raw.get("check_id")
    if not isinstance(check_id, str) or not check_id:
        raise TaskPlanError(
            f"plan steps[{index}].produces[{produces_name!r}].check.check_id must be a non-empty string"
        )
    params = raw.get("params", {})
    if not isinstance(params, dict):
        raise TaskPlanError(
            f"plan steps[{index}].produces[{produces_name!r}].check.params must be an object"
        )
    sentinel = raw.get("sentinel", False)
    if not isinstance(sentinel, bool):
        raise TaskPlanError(
            f"plan steps[{index}].produces[{produces_name!r}].check.sentinel must be a bool"
        )
    return Check(check_id=check_id, params=canonical_check_params(params), sentinel=sentinel)


def _validate_repeat(raw: Any, index: int, prior_siblings: list[Step]) -> Repeat | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise TaskPlanError(f"plan steps[{index}].repeat must be an object")
    has_until = "until" in raw
    has_for_each = "for_each" in raw
    if has_until and has_for_each:
        raise TaskPlanError(
            f"plan steps[{index}].repeat cannot have both 'until' and 'for_each'"
        )
    if not has_until and not has_for_each:
        raise TaskPlanError(
            f"plan steps[{index}].repeat must contain 'until' or 'for_each'"
        )
    if has_until:
        return _validate_repeat_until(raw, index)
    return _validate_repeat_for_each(raw["for_each"], index, prior_siblings)


def _validate_repeat_until(raw: dict[str, Any], index: int) -> RepeatUntil:
    condition = raw.get("until")
    if condition not in {"user_approves", "verifier_passes", "quorum"}:
        raise TaskPlanError(
            f"plan steps[{index}].repeat.until must be one of 'user_approves','verifier_passes','quorum', got {condition!r}"
        )
    max_iterations = raw.get("max_iterations")
    if not isinstance(max_iterations, int) or isinstance(max_iterations, bool) or max_iterations < 1:
        raise TaskPlanError(
            f"plan steps[{index}].repeat.max_iterations must be an int >= 1"
        )
    on_exhaust = raw.get("on_exhaust")
    if on_exhaust not in {"escalate", "fail"}:
        raise TaskPlanError(
            f"plan steps[{index}].repeat.on_exhaust must be 'escalate' or 'fail', got {on_exhaust!r}"
        )
    quorum_n = raw.get("quorum_n")
    if condition == "quorum":
        if not isinstance(quorum_n, int) or isinstance(quorum_n, bool) or quorum_n < 1:
            raise TaskPlanError(
                f"plan steps[{index}].repeat.quorum_n must be an int >= 1 when until='quorum'"
            )
    elif quorum_n is not None:
        raise TaskPlanError(
            f"plan steps[{index}].repeat.quorum_n only valid when until='quorum'"
        )
    return RepeatUntil(
        condition=condition,
        max_iterations=max_iterations,
        on_exhaust=on_exhaust,
        quorum_n=quorum_n,
    )


def _validate_repeat_for_each(raw: Any, index: int, prior_siblings: list[Step]) -> RepeatForEach:
    if not isinstance(raw, dict):
        raise TaskPlanError(
            f"plan steps[{index}].repeat.for_each must be an object"
        )
    has_items = "items" in raw
    has_from = "from" in raw
    if has_items == has_from:
        raise TaskPlanError(
            f"plan steps[{index}].repeat.for_each must have exactly one of 'items' or 'from'"
        )
    if has_items:
        items = raw["items"]
        if not isinstance(items, list) or not all(isinstance(x, str) and x for x in items):
            raise TaskPlanError(
                f"plan steps[{index}].repeat.for_each.items must be a list of non-empty strings"
            )
        return RepeatForEach(items_source="static", items=tuple(items), from_ref=None)
    from_ref = raw["from"]
    if not isinstance(from_ref, str) or not from_ref:
        raise TaskPlanError(
            f"plan steps[{index}].repeat.for_each.from must be a non-empty string"
        )
    target_id, produces_name = parse_from_ref(from_ref)
    target = next((s for s in prior_siblings if s.id == target_id), None)
    if target is None:
        raise TaskPlanError(
            f"plan steps[{index}].repeat.for_each.from references unknown prior sibling step {target_id!r}"
        )
    if not any(p.name == produces_name for p in target.produces):
        raise TaskPlanError(
            f"plan steps[{index}].repeat.for_each.from references unknown produces {produces_name!r} on step {target_id!r}"
        )
    return RepeatForEach(items_source="from", items=(), from_ref=from_ref)


def _reject_orchestrators_run(step: Step) -> None:
    """Reject leaf local-adapter steps that try to shell out to `astrid orchestrators run`."""
    if step.command is None:
        return
    try:
        tokens = shlex.split(step.command)
    except ValueError as exc:
        raise TaskPlanError(
            f"step {step.id!r}: command is not shell-parseable: {exc}"
        ) from exc
    tokens = _strip_astrid_prefix(tokens)
    if len(tokens) >= 2 and tokens[0] == "orchestrators" and tokens[1] == "run":
        raise TaskPlanError(
            f"step {step.id!r}: local-adapter command targets 'astrid orchestrators run'; use a group step (children) instead"
        )


def _strip_astrid_prefix(tokens: list[str]) -> list[str]:
    if (
        len(tokens) >= 3
        and Path(tokens[0]).name.startswith("python")
        and tokens[1:3] == ["-m", "astrid"]
    ):
        return tokens[3:]
    if tokens and Path(tokens[0]).name.endswith("astrid"):
        return tokens[1:]
    return tokens


def _assert_unique_paths(plan: TaskPlan) -> None:
    """Reject sibling-id collisions inside any one frame."""

    def _check(steps: tuple[Step, ...], prefix: tuple[str, ...]) -> None:
        seen: set[str] = set()
        for step in steps:
            if step.id in seen:
                location = STEP_PATH_SEP.join(prefix + (step.id,))
                raise TaskPlanError(
                    f"duplicate step id {step.id!r} among siblings at {location!r}"
                )
            seen.add(step.id)
            if step.children is not None:
                _check(step.children, prefix + (step.id,))

    _check(plan.steps, ())
