"""Code-first authoring helpers for ArtAgents conductors."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Callable

from artagents.contracts.schema import CachePolicy, CommandSpec, IsolationMetadata, Output, Port

from .schema import ConductorDefinition, ConductorValidationError, RuntimeSpec, validate_conductor_definition


class ConductorSpec:
    """Small code-first wrapper that normalizes to `ConductorDefinition`."""

    __slots__ = ("_definition",)

    def __init__(
        self,
        *,
        id: str,
        name: str,
        runtime: RuntimeSpec | dict[str, Any],
        kind: str = "external",
        version: str = "0.1.0",
        description: str = "",
        inputs: tuple[Port | dict[str, Any], ...] | list[Port | dict[str, Any]] = (),
        outputs: tuple[Output | dict[str, Any], ...] | list[Output | dict[str, Any]] = (),
        child_performers: tuple[str, ...] | list[str] = (),
        child_conductors: tuple[str, ...] | list[str] = (),
        cache: CachePolicy | dict[str, Any] | None = None,
        isolation: IsolationMetadata | dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        raw: dict[str, Any] = {
            "id": id,
            "name": name,
            "kind": kind,
            "version": version,
            "runtime": _to_plain(runtime),
            "inputs": [_to_plain(input_) for input_ in inputs],
            "outputs": [_to_plain(output) for output in outputs],
            "child_performers": list(child_performers),
            "child_conductors": list(child_conductors),
            "metadata": dict(metadata or {}),
        }
        if description:
            raw["description"] = description
        if cache is not None:
            raw["cache"] = _to_plain(cache)
        if isolation is not None:
            raw["isolation"] = _to_plain(isolation)
        self._definition = validate_conductor_definition(raw)

    @classmethod
    def from_definition(cls, definition: ConductorDefinition | dict[str, Any]) -> "ConductorSpec":
        spec = cls.__new__(cls)
        spec._definition = validate_conductor_definition(definition)
        return spec

    def to_definition(self) -> ConductorDefinition:
        return self._definition

    def to_dict(self) -> dict[str, Any]:
        return self._definition.to_dict()

    def to_json(self, *, indent: int | None = 2) -> str:
        return self._definition.to_json(indent=indent)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._definition, name)


def conductor(spec: ConductorSpec | ConductorDefinition | dict[str, Any] | None = None, **kwargs: Any) -> Any:
    """Create a conductor spec or decorate a callable with validated metadata."""

    resolved = ConductorSpec(**kwargs) if spec is None else _to_spec(spec)

    def decorate(target: Callable[..., Any]) -> Callable[..., Any]:
        target.conductor = resolved.to_definition()  # type: ignore[attr-defined]
        target.CONDUCTOR = resolved.to_definition()  # type: ignore[attr-defined]
        return target

    return decorate if kwargs or spec is not None else resolved


def _to_spec(value: ConductorSpec | ConductorDefinition | dict[str, Any]) -> ConductorSpec:
    if isinstance(value, ConductorSpec):
        return value
    return ConductorSpec.from_definition(value)


def _to_plain(value: Any) -> Any:
    if isinstance(value, ConductorSpec):
        return value.to_dict()
    if isinstance(value, ConductorDefinition):
        return value.to_dict()
    if isinstance(value, RuntimeSpec):
        return value.to_dict() if hasattr(value, "to_dict") else _drop_blank_defaults(asdict(value))
    if isinstance(value, CommandSpec):
        return _drop_blank_defaults(asdict(value))
    if is_dataclass(value):
        return _drop_blank_defaults(asdict(value))
    return value


def _drop_blank_defaults(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _drop_blank_defaults(item)
            for key, item in value.items()
            if item is not None and item != ""
        }
    if isinstance(value, list):
        return [_drop_blank_defaults(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_drop_blank_defaults(item) for item in value)
    return value


__all__ = [
    "CachePolicy",
    "CommandSpec",
    "ConductorSpec",
    "ConductorValidationError",
    "IsolationMetadata",
    "Output",
    "Port",
    "RuntimeSpec",
    "conductor",
]
