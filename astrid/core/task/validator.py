"""Single-entry six-invariant validator for plan mutations (Sprint 3 T7)."""

from __future__ import annotations

from typing import Any, Iterable, Literal

from astrid.core.task.plan import (
    ADAPTERS,
    Step,
    TaskPlan,
    TaskPlanError,
    _assert_unique_paths,
    _validate_plan,
    iter_steps_with_path,
    parse_from_ref,
)


InvariantId = Literal[
    "I1_schema",
    "I2_sibling_uniqueness",
    "I3_produces_refs",
    "I4_adapter_shape",
    "I5_repeat_source",
    "I6_lease_epoch_cas",
]

INVARIANTS: tuple[InvariantId, ...] = (
    "I1_schema",
    "I2_sibling_uniqueness",
    "I3_produces_refs",
    "I4_adapter_shape",
    "I5_repeat_source",
    "I6_lease_epoch_cas",
)


class MutationInvariantError(ValueError):
    """Raised when a plan mutation fails one of the six invariants."""

    def __init__(self, invariant_id: InvariantId, element: str, reason: str) -> None:
        super().__init__(f"[{invariant_id}] {element}: {reason}")
        self.invariant_id = invariant_id
        self.element = element
        self.reason = reason


def validate_mutation(
    prior: TaskPlan | None,
    proposed: TaskPlan,
    *,
    lease_epoch_actual: int,
    lease_epoch_expected: int,
) -> None:
    """Run all six invariants against the proposed effective tree. Total rejection on first failure.

    ``prior`` is unused by the invariant checks themselves but reserved for diff-aware
    sub-checks Sprint 5a may add. Pass None when there is no prior tree (initial plan).
    """
    _check_schema(proposed)
    _check_sibling_uniqueness(proposed)
    _check_produces_refs(proposed)
    _check_adapter_shape(proposed)
    _check_repeat_source(proposed)
    _check_lease_epoch(lease_epoch_actual, lease_epoch_expected)


# ---- I1: schema re-validate (round-trip through _validate_plan) ----

def _check_schema(proposed: TaskPlan) -> None:
    try:
        _validate_plan(proposed.to_dict())
    except TaskPlanError as exc:
        raise MutationInvariantError("I1_schema", "plan", str(exc)) from exc


# ---- I2: sibling-id uniqueness at every frame ----

def _check_sibling_uniqueness(proposed: TaskPlan) -> None:
    try:
        _assert_unique_paths(proposed)
    except TaskPlanError as exc:
        raise MutationInvariantError("I2_sibling_uniqueness", "plan", str(exc)) from exc


# ---- I3: produces reference integrity (including group-step re_export) ----

def _collect_step_index(proposed: TaskPlan) -> dict[str, Step]:
    """Map step.id -> Step for every step in the tree."""
    return {step.id: step for _path, step in iter_steps_with_path(proposed)}


def _check_produces_refs(proposed: TaskPlan) -> None:
    index = _collect_step_index(proposed)
    for path, step in iter_steps_with_path(proposed):
        if step.re_export is None:
            continue
        for name, ref in step.re_export:
            try:
                child_id, produces_name = parse_from_ref(ref)
            except TaskPlanError as exc:
                raise MutationInvariantError(
                    "I3_produces_refs",
                    f"{'/'.join(path)}.re_export[{name!r}]",
                    f"unparseable ref {ref!r}: {exc}",
                ) from exc
            target = index.get(child_id)
            if target is None:
                raise MutationInvariantError(
                    "I3_produces_refs",
                    f"{'/'.join(path)}.re_export[{name!r}]",
                    f"references unknown step {child_id!r}",
                )
            if not any(p.name == produces_name for p in target.produces):
                raise MutationInvariantError(
                    "I3_produces_refs",
                    f"{'/'.join(path)}.re_export[{name!r}]",
                    f"step {child_id!r} declares no produces named {produces_name!r}",
                )


# ---- I4: adapter declared + command shape per-adapter ----

def _check_adapter_shape(proposed: TaskPlan) -> None:
    for path, step in iter_steps_with_path(proposed):
        location = "/".join(path)
        if step.adapter not in ADAPTERS:
            raise MutationInvariantError(
                "I4_adapter_shape",
                location,
                f"adapter must be one of {ADAPTERS}, got {step.adapter!r}",
            )
        # Group steps don't carry commands; check applies to leaf steps only.
        if step.children is not None:
            continue
        if step.adapter == "manual":
            if step.command is None or not step.command.strip():
                raise MutationInvariantError(
                    "I4_adapter_shape",
                    location,
                    "manual adapter requires a non-empty command (dispatch payload)",
                )
        if step.adapter == "local":
            if step.command is None or not step.command.strip():
                raise MutationInvariantError(
                    "I4_adapter_shape",
                    location,
                    "local adapter requires a non-empty command",
                )
        # remote-artifact: command shape is permissive — runtime adapter rejects entirely.


# ---- I5: repeat.for_each.from_ref resolves to a real prior produces ----

def _check_repeat_source(proposed: TaskPlan) -> None:
    # Walk siblings frame-by-frame so "prior" semantics match _validate_repeat_for_each.
    def _walk_frame(steps: tuple[Step, ...], prefix: tuple[str, ...]) -> None:
        for index, step in enumerate(steps):
            location = "/".join(prefix + (step.id,))
            if (
                step.repeat is not None
                and getattr(step.repeat, "kind", None) == "for_each"
                and getattr(step.repeat, "items_source", None) == "from"
                and step.repeat.from_ref is not None
            ):
                try:
                    target_id, produces_name = parse_from_ref(step.repeat.from_ref)
                except TaskPlanError as exc:
                    raise MutationInvariantError(
                        "I5_repeat_source",
                        f"{location}.repeat.for_each.from",
                        f"unparseable ref {step.repeat.from_ref!r}: {exc}",
                    ) from exc
                priors = steps[:index]
                target = next((s for s in priors if s.id == target_id), None)
                if target is None:
                    raise MutationInvariantError(
                        "I5_repeat_source",
                        f"{location}.repeat.for_each.from",
                        f"references unknown prior sibling {target_id!r}",
                    )
                if not any(p.name == produces_name for p in target.produces):
                    raise MutationInvariantError(
                        "I5_repeat_source",
                        f"{location}.repeat.for_each.from",
                        f"prior sibling {target_id!r} declares no produces named {produces_name!r}",
                    )
            if step.children is not None:
                _walk_frame(step.children, prefix + (step.id,))

    _walk_frame(proposed.steps, ())


# ---- I6: lease-epoch CAS ----

def _check_lease_epoch(actual: int, expected: int) -> None:
    if actual != expected:
        raise MutationInvariantError(
            "I6_lease_epoch_cas",
            "lease.writer_epoch",
            f"expected {expected}, got {actual} (another writer mutated under you)",
        )


__all__ = [
    "INVARIANTS",
    "InvariantId",
    "MutationInvariantError",
    "validate_mutation",
]
