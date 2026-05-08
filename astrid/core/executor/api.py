"""Code-first authoring helpers for Astrid executors.

This module is intentionally a thin facade over :mod:`astrid.core.executor.schema`.
`ExecutorSpec` validates into the existing `ExecutorDefinition` model immediately so
folder executors do not introduce a second manifest schema.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Callable

from .schema import (
    ExecutorDefinition,
    ExecutorOutput,
    ExecutorPort,
    ExecutorValidationError,
    validate_executor_definition,
)


class ExecutorSpec:
    """Small code-first wrapper that normalizes to `ExecutorDefinition`."""

    __slots__ = ("_definition",)

    def __init__(
        self,
        *,
        id: str,
        name: str,
        kind: str = "external",
        version: str = "0.1.0",
        description: str = "",
        inputs: tuple[ExecutorPort | dict[str, Any], ...] | list[ExecutorPort | dict[str, Any]] = (),
        outputs: tuple[ExecutorOutput | dict[str, Any], ...] | list[ExecutorOutput | dict[str, Any]] = (),
        command: Any = None,
        cache: Any = None,
        conditions: tuple[Any, ...] | list[Any] = (),
        graph: Any = None,
        isolation: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        raw = {
            "id": id,
            "name": name,
            "kind": kind,
            "version": version,
            "inputs": [_to_plain(input_) for input_ in inputs],
            "outputs": [_to_plain(output) for output in outputs],
            "conditions": [_to_plain(condition) for condition in conditions],
            "metadata": dict(metadata or {}),
        }
        if description:
            raw["description"] = description
        if command is not None:
            raw["command"] = _to_plain(command)
        if cache is not None:
            raw["cache"] = _to_plain(cache)
        if graph is not None:
            raw["graph"] = _to_plain(graph)
        if isolation is not None:
            raw["isolation"] = _to_plain(isolation)
        self._definition = validate_executor_definition(raw)

    @classmethod
    def from_definition(cls, definition: ExecutorDefinition | dict[str, Any]) -> "ExecutorSpec":
        spec = cls.__new__(cls)
        spec._definition = validate_executor_definition(definition)
        return spec

    def to_definition(self) -> ExecutorDefinition:
        return self._definition

    def to_dict(self) -> dict[str, Any]:
        return self._definition.to_dict()

    def to_json(self, *, indent: int | None = 2) -> str:
        return self._definition.to_json(indent=indent)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._definition, name)


def executor(spec: ExecutorSpec | ExecutorDefinition | dict[str, Any] | None = None, **kwargs: Any) -> Any:
    """Create a executor spec or decorate a callable with validated executor metadata."""

    resolved = ExecutorSpec(**kwargs) if spec is None else _to_spec(spec)

    def decorate(target: Callable[..., Any]) -> Callable[..., Any]:
        target.executor = resolved.to_definition()  # type: ignore[attr-defined]
        target.EXECUTOR = resolved.to_definition()  # type: ignore[attr-defined]
        return target

    return decorate if kwargs or spec is not None else resolved


def _to_spec(value: ExecutorSpec | ExecutorDefinition | dict[str, Any]) -> ExecutorSpec:
    if isinstance(value, ExecutorSpec):
        return value
    return ExecutorSpec.from_definition(value)


def _to_plain(value: Any) -> Any:
    if isinstance(value, ExecutorSpec):
        return value.to_dict()
    if isinstance(value, ExecutorDefinition):
        return value.to_dict()
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
    "ExecutorOutput",
    "ExecutorPort",
    "ExecutorSpec",
    "ExecutorValidationError",
    "executor",
]
