"""Code-first authoring helpers for ArtAgents performers.

This module is intentionally a thin facade over :mod:`artagents.performers.schema`.
`PerformerSpec` validates into the existing `PerformerDefinition` model immediately so
folder performers do not introduce a second manifest schema.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Callable

from .schema import (
    PerformerDefinition,
    PerformerOutput,
    PerformerPort,
    PerformerValidationError,
    validate_performer_definition,
)


class PerformerSpec:
    """Small code-first wrapper that normalizes to `PerformerDefinition`."""

    __slots__ = ("_definition",)

    def __init__(
        self,
        *,
        id: str,
        name: str,
        kind: str = "external",
        version: str = "0.1.0",
        description: str = "",
        inputs: tuple[PerformerPort | dict[str, Any], ...] | list[PerformerPort | dict[str, Any]] = (),
        outputs: tuple[PerformerOutput | dict[str, Any], ...] | list[PerformerOutput | dict[str, Any]] = (),
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
        self._definition = validate_performer_definition(raw)

    @classmethod
    def from_definition(cls, definition: PerformerDefinition | dict[str, Any]) -> "PerformerSpec":
        spec = cls.__new__(cls)
        spec._definition = validate_performer_definition(definition)
        return spec

    def to_definition(self) -> PerformerDefinition:
        return self._definition

    def to_dict(self) -> dict[str, Any]:
        return self._definition.to_dict()

    def to_json(self, *, indent: int | None = 2) -> str:
        return self._definition.to_json(indent=indent)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._definition, name)


def performer(spec: PerformerSpec | PerformerDefinition | dict[str, Any] | None = None, **kwargs: Any) -> Any:
    """Create a performer spec or decorate a callable with validated performer metadata."""

    resolved = PerformerSpec(**kwargs) if spec is None else _to_spec(spec)

    def decorate(target: Callable[..., Any]) -> Callable[..., Any]:
        target.performer = resolved.to_definition()  # type: ignore[attr-defined]
        target.PERFORMER = resolved.to_definition()  # type: ignore[attr-defined]
        return target

    return decorate if kwargs or spec is not None else resolved


def _to_spec(value: PerformerSpec | PerformerDefinition | dict[str, Any]) -> PerformerSpec:
    if isinstance(value, PerformerSpec):
        return value
    return PerformerSpec.from_definition(value)


def _to_plain(value: Any) -> Any:
    if isinstance(value, PerformerSpec):
        return value.to_dict()
    if isinstance(value, PerformerDefinition):
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
    "PerformerOutput",
    "PerformerPort",
    "PerformerSpec",
    "PerformerValidationError",
    "performer",
]
