"""Task plan helpers."""

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


TASK_STEP_KINDS = ("code", "attested", "nested")
STEP_PATH_SEP = "/"


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
class CodeStep:
    id: str
    command: str
    produces: tuple[ProducesEntry, ...] = ()
    repeat: Repeat | None = None
    kind: Literal["code"] = "code"


@dataclass(frozen=True)
class AttestedStep:
    id: str
    command: str
    instructions: str
    ack: AckRule
    produces: tuple[ProducesEntry, ...] = ()
    repeat: Repeat | None = None
    kind: Literal["attested"] = "attested"


@dataclass(frozen=True)
class NestedStep:
    id: str
    plan: "TaskPlan"
    produces: tuple[ProducesEntry, ...] = ()
    repeat: Repeat | None = None
    kind: Literal["nested"] = "nested"


TaskPlanStep = Union[CodeStep, AttestedStep, NestedStep]


@dataclass(frozen=True)
class TaskPlan:
    plan_id: str
    version: int
    steps: tuple[TaskPlanStep, ...]

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
    if iteration is not None and item_id is not None:
        raise TaskPlanError("step_dir_for_path: iteration and item_id are mutually exclusive")
    base = project_dir(slug, root=root) / "runs" / run_id / "steps"
    for segment in plan_step_path:
        base = base / segment
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
    root: str | Path | None = None,
) -> Path:
    return step_dir_for_path(slug, run_id, (plan_step_id,), root=root)


def iter_steps_with_path(plan: TaskPlan) -> Iterator[tuple[tuple[str, ...], TaskPlanStep]]:
    """Yield ``(path, step)`` in pre-order for every step in the plan tree."""

    def _walk(steps: tuple[TaskPlanStep, ...], prefix: tuple[str, ...]) -> Iterator[tuple[tuple[str, ...], TaskPlanStep]]:
        for step in steps:
            path = prefix + (step.id,)
            yield path, step
            if isinstance(step, NestedStep):
                yield from _walk(step.plan.steps, path)

    yield from _walk(plan.steps, ())


def parse_from_ref(from_ref: str) -> tuple[str, str]:
    """Parse '<step-id>.produces.<name>' into (step_id, produces_name)."""
    sep = ".produces."
    idx = from_ref.find(sep)
    if idx <= 0 or idx + len(sep) >= len(from_ref):
        raise TaskPlanError(
            f"repeat.for_each.from must match '<step-id>.produces.<name>', got {from_ref!r}"
        )
    return from_ref[:idx], from_ref[idx + len(sep):]


def _step_to_dict(step: TaskPlanStep) -> dict[str, Any]:
    if isinstance(step, CodeStep):
        out: dict[str, Any] = {"id": step.id, "kind": "code", "command": step.command}
    elif isinstance(step, AttestedStep):
        out = {
            "id": step.id,
            "kind": "attested",
            "command": step.command,
            "instructions": step.instructions,
            "ack": {"kind": step.ack.kind},
        }
    elif isinstance(step, NestedStep):
        out = {
            "id": step.id,
            "kind": "nested",
            "plan": step.plan.to_dict(),
        }
    else:
        raise TaskPlanError(f"unknown step type: {type(step)!r}")
    if step.produces:
        out["produces"] = _produces_to_dict(step.produces)
    if step.repeat is not None:
        out["repeat"] = _repeat_to_dict(step.repeat)
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


def _validate_plan(payload: Any, *, _is_root: bool = True) -> TaskPlan:
    if not isinstance(payload, dict):
        raise TaskPlanError("plan must be an object")
    plan_id = payload.get("plan_id")
    version = payload.get("version")
    steps = payload.get("steps")
    if not isinstance(plan_id, str) or not plan_id:
        raise TaskPlanError("plan plan_id must be a non-empty string")
    if version != 1 or isinstance(version, bool):
        raise TaskPlanError("plan version must be 1")
    if not isinstance(steps, list):
        raise TaskPlanError("plan steps must be a list")

    validated_steps: list[TaskPlanStep] = []
    for index, step in enumerate(steps):
        validated_steps.append(_validate_step(step, index, validated_steps))

    plan = TaskPlan(plan_id=plan_id, version=1, steps=tuple(validated_steps))
    if _is_root:
        _assert_unique_paths(plan)
    return plan


def _validate_step(step: Any, index: int, prior_siblings: list[TaskPlanStep]) -> TaskPlanStep:
    if not isinstance(step, dict):
        raise TaskPlanError(f"plan steps[{index}] must be an object")
    kind = step.get("kind", "code")
    if kind == "code":
        return _validate_code_step(step, index, prior_siblings)
    if kind == "attested":
        return _validate_attested_step(step, index, prior_siblings)
    if kind == "nested":
        return _validate_nested_step(step, index, prior_siblings)
    raise TaskPlanError(
        f"plan steps[{index}].kind must be one of {TASK_STEP_KINDS}, got {kind!r}"
    )


def _validate_code_step(step: dict[str, Any], index: int, prior_siblings: list[TaskPlanStep]) -> CodeStep:
    step_id = step.get("id")
    command = step.get("command")
    if not isinstance(step_id, str) or not step_id:
        raise TaskPlanError(f"plan steps[{index}].id must be a non-empty string")
    if not isinstance(command, str) or not command:
        raise TaskPlanError(f"plan steps[{index}].command must be a non-empty string")
    _reject_orchestrators_run(command, index)
    produces = _validate_produces(step.get("produces"), index, allow_legacy_list=True)
    repeat = _validate_repeat(step.get("repeat"), index, prior_siblings)
    return CodeStep(
        id=validate_run_id(step_id),
        command=command,
        produces=produces,
        repeat=repeat,
    )


def _validate_attested_step(step: dict[str, Any], index: int, prior_siblings: list[TaskPlanStep]) -> AttestedStep:
    step_id = step.get("id")
    command = step.get("command")
    instructions = step.get("instructions")
    raw_produces = step.get("produces")
    ack = step.get("ack")
    if not isinstance(step_id, str) or not step_id:
        raise TaskPlanError(f"plan steps[{index}].id must be a non-empty string")
    if not isinstance(command, str) or not command:
        raise TaskPlanError(f"plan steps[{index}].command must be a non-empty string")
    if not isinstance(instructions, str) or not instructions:
        raise TaskPlanError(
            f"plan steps[{index}].instructions must be a non-empty string for attested step"
        )
    if isinstance(raw_produces, list) and raw_produces:
        raise TaskPlanError(
            f"plan steps[{index}].produces is a sentinel-only list; attested produces require a semantic check (use dict form with non-sentinel check)"
        )
    produces = _validate_produces(raw_produces, index, allow_legacy_list=False)
    for entry in produces:
        if entry.check.sentinel:
            raise TaskPlanError(
                f"plan steps[{index}].produces[{entry.name!r}] uses sentinel-only check {entry.check.check_id!r}; attested produces requires a semantic check"
            )
    if not isinstance(ack, dict):
        raise TaskPlanError(f"plan steps[{index}].ack must be an object")
    ack_kind = ack.get("kind")
    if ack_kind not in {"agent", "actor"}:
        raise TaskPlanError(
            f"plan steps[{index}].ack.kind must be 'agent' or 'actor', got {ack_kind!r}"
        )
    repeat = _validate_repeat(step.get("repeat"), index, prior_siblings)
    return AttestedStep(
        id=validate_run_id(step_id),
        command=command,
        instructions=instructions,
        produces=produces,
        ack=AckRule(kind=ack_kind),
        repeat=repeat,
    )


def _validate_nested_step(step: dict[str, Any], index: int, prior_siblings: list[TaskPlanStep]) -> NestedStep:
    step_id = step.get("id")
    child_plan = step.get("plan")
    if not isinstance(step_id, str) or not step_id:
        raise TaskPlanError(f"plan steps[{index}].id must be a non-empty string")
    if not isinstance(child_plan, dict):
        raise TaskPlanError(
            f"plan steps[{index}].plan must be a nested plan object"
        )
    nested = _validate_plan(child_plan, _is_root=False)
    produces = _validate_produces(step.get("produces"), index, allow_legacy_list=False)
    repeat = _validate_repeat(step.get("repeat"), index, prior_siblings)
    return NestedStep(
        id=validate_run_id(step_id),
        plan=nested,
        produces=produces,
        repeat=repeat,
    )


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
        f"plan steps[{index}].produces must be a dict (or legacy list for code steps)"
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


def _validate_repeat(raw: Any, index: int, prior_siblings: list[TaskPlanStep]) -> Repeat | None:
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


def _validate_repeat_for_each(raw: Any, index: int, prior_siblings: list[TaskPlanStep]) -> RepeatForEach:
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


def _reject_orchestrators_run(command: str, index: int) -> None:
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        raise TaskPlanError(
            f"plan steps[{index}].command is not shell-parseable: {exc}"
        ) from exc
    tokens = _strip_astrid_prefix(tokens)
    if len(tokens) >= 2 and tokens[0] == "orchestrators" and tokens[1] == "run":
        raise TaskPlanError(
            "code step argv targets 'astrid orchestrators run'; use a nested step"
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
    """Reject sibling-id collisions inside any one frame.

    Identical leaf ids in different subtrees are accepted because their full paths differ.
    """

    def _check(steps: tuple[TaskPlanStep, ...], prefix: tuple[str, ...]) -> None:
        seen: set[str] = set()
        for step in steps:
            if step.id in seen:
                location = STEP_PATH_SEP.join(prefix + (step.id,))
                raise TaskPlanError(
                    f"duplicate step id {step.id!r} among siblings at {location!r}"
                )
            seen.add(step.id)
            if isinstance(step, NestedStep):
                _check(step.plan.steps, prefix + (step.id,))

    _check(plan.steps, ())
