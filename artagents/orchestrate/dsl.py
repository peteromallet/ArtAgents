"""DSL builders for ArtAgents task-mode orchestrators (Phase 4).

Authors construct task plans in Python using the helpers exported from
``artagents.orchestrate``. The DSL emits a JSON payload byte-shape-equivalent
to the schema accepted by ``artagents.core.task.plan.load_plan``.

Construction-time guards are intentional: the typo trap on
``step.<missing_produces>``, sentinel-only attested rejection, the
``orchestrators run`` argv guard, reserved-attribute collisions, and
duplicate sibling-id detection all raise ``OrchestrateDefinitionError`` at
definition time so authoring errors surface immediately.
"""

from __future__ import annotations

import json
import os
import shlex
import tempfile
from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple, Union

from artagents.core.task.plan import (
    TaskPlanError,
    _strip_artagents_prefix,
    load_plan,
)
from artagents.verify import Check, canonical_check_params


class OrchestrateDefinitionError(Exception):
    """Raised when an orchestrator DSL definition is invalid."""


_RESERVED_ATTRS = frozenset(
    {"id", "kind", "command", "argv", "plan", "produces", "repeat", "instructions", "ack"}
)
_VALID_UNTIL = frozenset({"user_approves", "verifier_passes", "quorum"})
_VALID_ON_EXHAUST = frozenset({"escalate", "fail"})
_VALID_ACK_KINDS = frozenset({"agent", "actor"})


@dataclass(frozen=True)
class _ProducesHandle:
    step_id: str
    name: str

    def __str__(self) -> str:
        return f"{self.step_id}.produces.{self.name}"


@dataclass(frozen=True)
class _RepeatUntilSpec:
    condition: str
    max_iterations: int
    on_exhaust: str
    quorum_n: Optional[int] = None


@dataclass(frozen=True)
class _RepeatForEachSpec:
    items: Optional[Tuple[str, ...]]
    from_ref: Any  # str | _ProducesHandle | None


_RepeatSpec = Union[_RepeatUntilSpec, _RepeatForEachSpec]


class _StepHandle:
    """A typed reference to a declared step.

    Attribute access on an unknown name first looks up declared produces and
    returns a ``_ProducesHandle``; misses raise ``OrchestrateDefinitionError``
    so authoring typos fail at definition time rather than at runtime.
    """

    def __init__(
        self,
        *,
        id: str,
        kind: str,
        command: Optional[str] = None,
        argv: Optional[Tuple[str, ...]] = None,
        plan: Any = None,
        produces: Optional[dict] = None,
        repeat: Optional[_RepeatSpec] = None,
        instructions: Optional[str] = None,
        ack: Optional[dict] = None,
        cost_hint_usd: Optional[float] = None,
    ) -> None:
        self.id = id
        self.kind = kind
        self.command = command
        self.argv = argv
        self.plan = plan
        self.produces = produces or {}
        self.repeat = repeat
        self.instructions = instructions
        self.ack = ack
        self.cost_hint_usd = cost_hint_usd

    def __getattr__(self, name: str) -> _ProducesHandle:
        produces = self.__dict__.get("produces", {})
        if name in produces:
            return _ProducesHandle(self.__dict__.get("id", "<unknown>"), name)
        step_id = self.__dict__.get("id", "<unknown>")
        declared = ", ".join(sorted(produces.keys())) if produces else "<none>"
        raise OrchestrateDefinitionError(
            f"step {step_id!r} has no produces {name!r}; declared produces: [{declared}]"
        )

    def __repr__(self) -> str:
        return f"_StepHandle(id={self.id!r}, kind={self.kind!r})"


class _PlanBuilder:
    """A tree of steps; emits a load_plan-compatible JSON payload."""

    def __init__(self, plan_id: str, steps: list) -> None:
        if not isinstance(plan_id, str) or not plan_id:
            raise OrchestrateDefinitionError("plan_id must be a non-empty string")
        if not isinstance(steps, list):
            raise OrchestrateDefinitionError(
                f"plan {plan_id!r} steps must be a list, got {type(steps).__name__}"
            )
        seen: set = set()
        for index, step in enumerate(steps):
            if not isinstance(step, _StepHandle):
                raise OrchestrateDefinitionError(
                    f"plan {plan_id!r} steps[{index}] must be a _StepHandle, "
                    f"got {type(step).__name__}"
                )
            if step.id in seen:
                raise OrchestrateDefinitionError(
                    f"plan {plan_id!r} has duplicate sibling step id {step.id!r}"
                )
            seen.add(step.id)
        self.plan_id = plan_id
        self.steps: Tuple[_StepHandle, ...] = tuple(steps)

    def _build_payload(
        self,
        *,
        _resolver: Optional[Callable[..., "_PlanBuilder"]] = None,
        _visiting: Optional[set] = None,
    ) -> dict:
        if _visiting is None:
            _visiting = set()
        if self.plan_id in _visiting:
            chain = " -> ".join(sorted(_visiting) + [self.plan_id])
            raise OrchestrateDefinitionError(
                f"nested cycle: plan {self.plan_id!r} re-entered (chain: {chain})"
            )
        next_visiting = _visiting | {self.plan_id}
        return {
            "plan_id": self.plan_id,
            "version": 1,
            "steps": [
                _step_to_dict(step, _resolver=_resolver, _visiting=next_visiting)
                for step in self.steps
            ],
        }

    def to_dict(
        self,
        *,
        _resolver: Optional[Callable[..., "_PlanBuilder"]] = None,
        _visiting: Optional[set] = None,
    ) -> dict:
        payload = self._build_payload(_resolver=_resolver, _visiting=_visiting)
        # Round-trip through the public load_plan validator (FLAG-002).
        fp = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        )
        try:
            json.dump(payload, fp)
            fp.flush()
            tmp_path = fp.name
        finally:
            fp.close()
        try:
            load_plan(tmp_path)
        except TaskPlanError as exc:
            raise OrchestrateDefinitionError(
                f"DSL output for plan {self.plan_id!r} failed validation: {exc}"
            ) from exc
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        return payload

    def __repr__(self) -> str:
        return f"_PlanBuilder(plan_id={self.plan_id!r}, steps={len(self.steps)})"


def _step_to_dict(
    step: _StepHandle,
    *,
    _resolver: Optional[Callable[..., _PlanBuilder]],
    _visiting: set,
) -> dict:
    if step.kind == "code":
        out: dict = {"id": step.id, "kind": "code", "command": step.command}
    elif step.kind == "attested":
        out = {
            "id": step.id,
            "kind": "attested",
            "command": step.command,
            "instructions": step.instructions,
            "ack": dict(step.ack or {}),
        }
    elif step.kind == "nested":
        nested_plan = step.plan
        if isinstance(nested_plan, _PlanBuilder):
            child_payload = nested_plan._build_payload(
                _resolver=_resolver, _visiting=_visiting
            )
        elif isinstance(nested_plan, str):
            if _resolver is None:
                raise OrchestrateDefinitionError(
                    f"nested step {step.id!r} uses string plan ref {nested_plan!r}; "
                    "compile via artagents.orchestrate.compile.compile_to_path "
                    "or pass _resolver= to to_dict()"
                )
            sub_builder = _resolver(nested_plan, _visiting=_visiting)
            if not isinstance(sub_builder, _PlanBuilder):
                raise OrchestrateDefinitionError(
                    f"nested step {step.id!r} resolver returned "
                    f"{type(sub_builder).__name__}, expected _PlanBuilder"
                )
            child_payload = sub_builder._build_payload(
                _resolver=_resolver, _visiting=_visiting
            )
        else:
            raise OrchestrateDefinitionError(
                f"nested step {step.id!r} plan must be _PlanBuilder or "
                f"qualified id string, got {type(nested_plan).__name__}"
            )
        out = {"id": step.id, "kind": "nested", "plan": child_payload}
    else:
        raise OrchestrateDefinitionError(
            f"step {step.id!r} has unknown kind {step.kind!r}"
        )

    if step.produces:
        out["produces"] = _produces_to_dict(step.produces)
    if step.repeat is not None:
        out["repeat"] = _repeat_to_dict(step.repeat)
    return out


def _produces_to_dict(produces: dict) -> dict:
    out: dict = {}
    for name in sorted(produces.keys()):
        path, check = produces[name]
        out[name] = {
            "path": path,
            "check": {
                "check_id": check.check_id,
                "params": canonical_check_params(check.params),
                "sentinel": check.sentinel,
            },
        }
    return out


def _repeat_to_dict(repeat: _RepeatSpec) -> dict:
    if isinstance(repeat, _RepeatUntilSpec):
        out: dict = {
            "until": repeat.condition,
            "max_iterations": repeat.max_iterations,
            "on_exhaust": repeat.on_exhaust,
        }
        if repeat.quorum_n is not None:
            out["quorum_n"] = repeat.quorum_n
        return out
    if isinstance(repeat, _RepeatForEachSpec):
        if repeat.items is not None:
            return {"for_each": {"items": list(repeat.items)}}
        return {"for_each": {"from": str(repeat.from_ref)}}
    raise OrchestrateDefinitionError(
        f"unknown repeat spec type: {type(repeat).__name__}"
    )


def _normalize_produces(raw: Any, step_id: str, *, kind: str) -> dict:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise OrchestrateDefinitionError(
            f"step {step_id!r} produces must be a dict, got {type(raw).__name__}"
        )
    out: dict = {}
    for name, value in raw.items():
        if not isinstance(name, str) or not name:
            raise OrchestrateDefinitionError(
                f"step {step_id!r} produces names must be non-empty strings"
            )
        if name in _RESERVED_ATTRS:
            raise OrchestrateDefinitionError(
                f"step {step_id!r} produces name {name!r} collides with reserved "
                f"_StepHandle attribute; choose a different name"
            )
        check, path = _coerce_produces_value(value, step_id, name)
        if kind == "attested" and check.sentinel:
            raise OrchestrateDefinitionError(
                f"attested step {step_id!r} produces[{name!r}] uses sentinel-only "
                f"check {check.check_id!r}; supply a semantic check (e.g. "
                f"json_file(), audio_duration_min(...), image_dimensions(...))"
            )
        out[name] = (path, check)
    return out


def _coerce_produces_value(value: Any, step_id: str, name: str) -> Tuple[Check, str]:
    """Accept a bare ``Check`` (path defaults to the produces name) or a
    ``(check, path)`` tuple. Anything else raises.
    """
    if isinstance(value, Check):
        return value, name
    if isinstance(value, tuple) and len(value) == 2:
        a, b = value
        if isinstance(a, Check) and isinstance(b, str) and b:
            return a, b
        if isinstance(b, Check) and isinstance(a, str) and a:
            return b, a
    raise OrchestrateDefinitionError(
        f"step {step_id!r} produces[{name!r}] must be a Check or (check, path) "
        f"tuple, got {type(value).__name__}"
    )


def _normalize_argv(argv: Any, step_id: str) -> Tuple[str, ...]:
    if not isinstance(argv, list) or not argv:
        raise OrchestrateDefinitionError(
            f"code step {step_id!r} argv must be a non-empty list"
        )
    out: list = []
    for index, element in enumerate(argv):
        if isinstance(element, _ProducesHandle):
            out.append(str(element))
        elif isinstance(element, str):
            out.append(element)
        else:
            raise OrchestrateDefinitionError(
                f"code step {step_id!r} argv[{index}] must be str or "
                f"_ProducesHandle, got {type(element).__name__}"
            )
    return tuple(out)


def _reject_orchestrators_run_argv(argv: Tuple[str, ...], step_id: str) -> None:
    tokens = _strip_artagents_prefix(list(argv))
    if len(tokens) >= 2 and tokens[0] == "orchestrators" and tokens[1] == "run":
        raise OrchestrateDefinitionError(
            f"code step {step_id!r} argv targets 'artagents orchestrators run'; "
            "use a nested(plan=...) step instead"
        )


def _normalize_repeat(repeat: Any, step_id: str) -> Optional[_RepeatSpec]:
    if repeat is None:
        return None
    if not isinstance(repeat, (_RepeatUntilSpec, _RepeatForEachSpec)):
        raise OrchestrateDefinitionError(
            f"step {step_id!r} repeat must come from repeat_until() or "
            f"repeat_for_each(), got {type(repeat).__name__}"
        )
    return repeat


def _normalize_ack(ack: Any, step_id: str) -> dict:
    if isinstance(ack, str):
        kind = ack
    elif isinstance(ack, dict) and "kind" in ack:
        kind = ack["kind"]
    else:
        raise OrchestrateDefinitionError(
            f"attested step {step_id!r} ack must be 'agent', 'actor', or "
            f"a dict with 'kind'; got {type(ack).__name__}"
        )
    if kind not in _VALID_ACK_KINDS:
        raise OrchestrateDefinitionError(
            f"attested step {step_id!r} ack.kind must be one of "
            f"{sorted(_VALID_ACK_KINDS)}, got {kind!r}"
        )
    return {"kind": kind}


def code(
    step_id: str,
    *,
    argv: list,
    produces: Optional[dict] = None,
    repeat: Optional[_RepeatSpec] = None,
    cost_hint_usd: Optional[float] = None,
) -> _StepHandle:
    if not isinstance(step_id, str) or not step_id:
        raise OrchestrateDefinitionError("code step_id must be a non-empty string")
    normalized_argv = _normalize_argv(argv, step_id)
    _reject_orchestrators_run_argv(normalized_argv, step_id)
    command = shlex.join(normalized_argv)
    produces_dict = _normalize_produces(produces, step_id, kind="code")
    repeat_spec = _normalize_repeat(repeat, step_id)
    return _StepHandle(
        id=step_id,
        kind="code",
        command=command,
        argv=normalized_argv,
        produces=produces_dict,
        repeat=repeat_spec,
        cost_hint_usd=cost_hint_usd,
    )


def attested(
    step_id: str,
    *,
    command: str,
    instructions: str,
    ack: Any,
    produces: Optional[dict] = None,
    repeat: Optional[_RepeatSpec] = None,
    cost_hint_usd: Optional[float] = None,
) -> _StepHandle:
    if not isinstance(step_id, str) or not step_id:
        raise OrchestrateDefinitionError("attested step_id must be a non-empty string")
    if not isinstance(command, str) or not command:
        raise OrchestrateDefinitionError(
            f"attested step {step_id!r} command must be a non-empty string"
        )
    if not isinstance(instructions, str) or not instructions:
        raise OrchestrateDefinitionError(
            f"attested step {step_id!r} instructions must be a non-empty string"
        )
    ack_dict = _normalize_ack(ack, step_id)
    produces_dict = _normalize_produces(produces, step_id, kind="attested")
    repeat_spec = _normalize_repeat(repeat, step_id)
    return _StepHandle(
        id=step_id,
        kind="attested",
        command=command,
        instructions=instructions,
        ack=ack_dict,
        produces=produces_dict,
        repeat=repeat_spec,
        cost_hint_usd=cost_hint_usd,
    )


def nested(
    step_id: str,
    *,
    plan: Any,
    produces: Optional[dict] = None,
    repeat: Optional[_RepeatSpec] = None,
    cost_hint_usd: Optional[float] = None,
) -> _StepHandle:
    if not isinstance(step_id, str) or not step_id:
        raise OrchestrateDefinitionError("nested step_id must be a non-empty string")
    if not isinstance(plan, (_PlanBuilder, str)):
        raise OrchestrateDefinitionError(
            f"nested step {step_id!r} plan must be a _PlanBuilder or qualified "
            f"id string, got {type(plan).__name__}"
        )
    if isinstance(plan, str) and not plan:
        raise OrchestrateDefinitionError(
            f"nested step {step_id!r} plan string must be non-empty"
        )
    produces_dict = _normalize_produces(produces, step_id, kind="nested")
    repeat_spec = _normalize_repeat(repeat, step_id)
    return _StepHandle(
        id=step_id,
        kind="nested",
        plan=plan,
        produces=produces_dict,
        repeat=repeat_spec,
        cost_hint_usd=cost_hint_usd,
    )


def repeat_until(
    condition: str,
    *,
    max_iterations: int,
    on_exhaust: str,
    quorum_n: Optional[int] = None,
) -> _RepeatUntilSpec:
    if condition not in _VALID_UNTIL:
        raise OrchestrateDefinitionError(
            f"repeat_until condition must be one of {sorted(_VALID_UNTIL)}, "
            f"got {condition!r}"
        )
    if not isinstance(max_iterations, int) or isinstance(max_iterations, bool) or max_iterations < 1:
        raise OrchestrateDefinitionError(
            f"repeat_until max_iterations must be an int >= 1, got {max_iterations!r}"
        )
    if on_exhaust not in _VALID_ON_EXHAUST:
        raise OrchestrateDefinitionError(
            f"repeat_until on_exhaust must be one of {sorted(_VALID_ON_EXHAUST)}, "
            f"got {on_exhaust!r}"
        )
    if condition == "quorum":
        if not isinstance(quorum_n, int) or isinstance(quorum_n, bool) or quorum_n < 1:
            raise OrchestrateDefinitionError(
                "repeat_until quorum_n must be an int >= 1 when condition='quorum'"
            )
    elif quorum_n is not None:
        raise OrchestrateDefinitionError(
            "repeat_until quorum_n is only valid when condition='quorum'"
        )
    return _RepeatUntilSpec(
        condition=condition,
        max_iterations=max_iterations,
        on_exhaust=on_exhaust,
        quorum_n=quorum_n,
    )


def repeat_for_each(
    items: Optional[list] = None,
    *,
    from_: Any = None,
) -> _RepeatForEachSpec:
    if (items is None) == (from_ is None):
        raise OrchestrateDefinitionError(
            "repeat_for_each requires exactly one of items= or from_="
        )
    if items is not None:
        if not isinstance(items, list) or not items or not all(
            isinstance(x, str) and x for x in items
        ):
            raise OrchestrateDefinitionError(
                "repeat_for_each items must be a non-empty list of non-empty strings"
            )
        return _RepeatForEachSpec(items=tuple(items), from_ref=None)
    if not isinstance(from_, (_ProducesHandle, str)) or (
        isinstance(from_, str) and not from_
    ):
        raise OrchestrateDefinitionError(
            "repeat_for_each from_ must be a non-empty string or _ProducesHandle"
        )
    return _RepeatForEachSpec(items=None, from_ref=from_)


def plan(plan_id: str, steps: list) -> _PlanBuilder:
    return _PlanBuilder(plan_id, steps)


def orchestrator(plan_id: str) -> Callable[[Any], _PlanBuilder]:
    if not isinstance(plan_id, str) or not plan_id:
        raise OrchestrateDefinitionError("orchestrator plan_id must be a non-empty string")

    def _decorator(target: Any) -> _PlanBuilder:
        if isinstance(target, _PlanBuilder):
            return target
        if isinstance(target, list):
            return _PlanBuilder(plan_id, target)
        if callable(target):
            result = target()
            if isinstance(result, _PlanBuilder):
                return result
            if isinstance(result, list):
                return _PlanBuilder(plan_id, result)
            raise OrchestrateDefinitionError(
                f"@orchestrator({plan_id!r}) target returned "
                f"{type(result).__name__}; expected _PlanBuilder or list of steps"
            )
        raise OrchestrateDefinitionError(
            f"@orchestrator({plan_id!r}) decorated object must be a callable, "
            f"_PlanBuilder, or list, got {type(target).__name__}"
        )

    return _decorator
