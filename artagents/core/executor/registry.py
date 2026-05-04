"""Registry and discovery helpers for ArtAgents executors."""

from __future__ import annotations

import json
from dataclasses import replace
from types import MappingProxyType
from typing import Any, Iterable

from artagents.core.pack import discover_packs, iter_executor_roots, validate_content_id_in_pack

from .banodoco_catalog import BanodocoCatalogConfig, load_banodoco_catalog_executors
from .folder import load_folder_executors
from .schema import ExecutorDefinition, ExecutorValidationError, validate_executor_definition


BUILTIN_STEP_ORDER: tuple[str, ...] = (
    "transcribe",
    "scenes",
    "quality_zones",
    "shots",
    "triage",
    "scene_describe",
    "quote_scout",
    "pool_build",
    "pool_merge",
    "arrange",
    "cut",
    "refine",
    "render",
    "editor_review",
    "validate",
)


class ExecutorRegistryError(ExecutorValidationError):
    """Raised when a executor registry is inconsistent."""


class ExecutorRegistry:
    """Small in-memory registry keyed by executor id."""

    def __init__(self, executors: Iterable[ExecutorDefinition | dict[str, Any]] = ()) -> None:
        self._executors: dict[str, ExecutorDefinition] = {}
        for executor in executors:
            self.register(executor)

    def register(self, executor: ExecutorDefinition | dict[str, Any]) -> ExecutorDefinition:
        definition = validate_executor_definition(executor)
        if definition.id in self._executors:
            raise ExecutorRegistryError(f"duplicate executor id {definition.id!r}")
        self._executors[definition.id] = definition
        return definition

    def get(self, executor_id: str) -> ExecutorDefinition:
        try:
            return self._executors[executor_id]
        except KeyError as exc:
            raise KeyError(f"unknown executor id {executor_id!r}") from exc

    def list(self, kind: str | None = None) -> tuple[ExecutorDefinition, ...]:
        if kind is not None and kind not in {"built_in", "external"}:
            raise ExecutorRegistryError("kind must be one of ['built_in', 'external']")
        executors = self._executors.values()
        if kind is not None:
            executors = [executor for executor in executors if executor.kind == kind]
        return tuple(sorted(executors, key=lambda executor: executor.id))

    def validate_all(self) -> tuple[ExecutorDefinition, ...]:
        for executor in self._executors.values():
            validate_executor_definition(executor)
        self._validate_graph_references()
        return self.list()

    def to_dict(self, kind: str | None = None) -> dict[str, Any]:
        return {"executors": [executor.to_dict() for executor in self.list(kind=kind)]}

    def to_json(self, *, kind: str | None = None, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(kind=kind), indent=indent, sort_keys=True)

    def as_mapping(self) -> MappingProxyType[str, ExecutorDefinition]:
        return MappingProxyType(dict(self._executors))

    def _validate_graph_references(self) -> None:
        known_ids = set(self._executors)
        for executor in self._executors.values():
            for dependency in executor.graph.depends_on:
                if dependency not in known_ids:
                    raise ExecutorRegistryError(f"executor {executor.id!r} depends on unknown executor {dependency!r}")
                if dependency == executor.id:
                    raise ExecutorRegistryError(f"executor {executor.id!r} cannot depend on itself")


def load_default_registry(banodoco_config: BanodocoCatalogConfig | None = None) -> ExecutorRegistry:
    registry = ExecutorRegistry()
    for executor in load_pack_executors():
        registry.register(executor)
    if banodoco_config is not None and banodoco_config.enabled:
        for executor in load_banodoco_catalog_executors(banodoco_config):
            registry.register(executor)
    registry.validate_all()
    return registry


def load_pack_executors() -> tuple[ExecutorDefinition, ...]:
    executors: list[ExecutorDefinition] = []
    for pack in discover_packs():
        for root in iter_executor_roots(pack):
            for executor in load_folder_executors(root):
                validate_content_id_in_pack(executor.id, pack, content_type="executor")
                executors.append(_attach_pack_metadata(executor, pack.id))
    return tuple(executors)


def _attach_pack_metadata(executor: ExecutorDefinition, pack_id: str) -> ExecutorDefinition:
    metadata = dict(executor.metadata)
    metadata.setdefault("pack_id", pack_id)
    metadata["source"] = "pack"
    return validate_executor_definition(replace(executor, metadata=metadata))


__all__ = [
    "BUILTIN_STEP_ORDER",
    "ExecutorRegistry",
    "ExecutorRegistryError",
    "BanodocoCatalogConfig",
    "load_pack_executors",
    "load_default_registry",
]
